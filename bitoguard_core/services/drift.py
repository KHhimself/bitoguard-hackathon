"""Feature drift detection service (MONITORING-001).

Compares the distribution of numeric features between the two most recent
snapshots and flags statistically significant shifts that might indicate
upstream data quality issues or model input degradation.

Drift is measured using three complementary signals:
  1. Zero-rate change — fraction of users with a zero value
  2. Mean shift — relative change in the column mean
  3. Std shift — relative change in the standard deviation

A feature is flagged as drifted when *any* signal exceeds its threshold.
Thresholds are conservative defaults; adjust via config if needed.

Additionally, score distribution drift (PSI) is tracked between scoring runs
to detect model degradation or upstream data quality changes before they
impact production F1. PSI < 0.10 = stable, 0.10-0.25 = moderate, > 0.25 = severe.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import load_settings
from db.store import DuckDBStore

logger = logging.getLogger(__name__)

# ── Drift thresholds ──────────────────────────────────────────────────────────
ZERO_RATE_ABS_DELTA_THRESHOLD = 0.15    # 15 percentage-point change in zero-rate
MEAN_REL_CHANGE_THRESHOLD = 0.50        # 50% relative change in mean
STD_REL_CHANGE_THRESHOLD = 0.50         # 50% relative change in std

# Columns excluded from drift checks (IDs, dates, categorical)
_SKIP_COLUMNS = frozenset({
    "user_id", "snapshot_date", "feature_snapshot_id", "feature_version",
    "kyc_level", "occupation", "declared_source_of_funds", "segment",
    "monthly_income_twd", "expected_monthly_volume_twd",
})


@dataclass
class FeatureDriftResult:
    snapshot_from: str
    snapshot_to: str
    drifted_features: list[dict[str, Any]]
    total_checked: int
    total_drifted: int
    health_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def _drift_cache_path(settings) -> Path:
    return settings.artifact_dir / "drift_report.json"


def _load_cached_result(cache_path: Path, date_from: str, date_to: str) -> FeatureDriftResult | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("snapshot_from") != date_from or payload.get("snapshot_to") != date_to:
        return None
    return FeatureDriftResult(
        snapshot_from=payload["snapshot_from"],
        snapshot_to=payload["snapshot_to"],
        drifted_features=payload.get("drifted_features", []),
        total_checked=int(payload.get("total_checked", 0)),
        total_drifted=int(payload.get("total_drifted", 0)),
        health_ok=bool(payload.get("health_ok", True)),
    )


def _write_cached_result(cache_path: Path, result: FeatureDriftResult) -> None:
    cache_path.write_text(result.to_json(), encoding="utf-8")


def _relative_change(old: float, new: float) -> float:
    if abs(old) < 1e-9:
        return 0.0 if abs(new) < 1e-9 else float("inf")
    return abs((new - old) / old)


def _zero_rate(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float((series == 0).sum() / len(series))


def detect_drift(
    snapshot_from: pd.DataFrame,
    snapshot_to: pd.DataFrame,
    date_from: str,
    date_to: str,
) -> FeatureDriftResult:
    """Compare feature distributions between two snapshots.

    Args:
        snapshot_from: Feature snapshot for the earlier date.
        snapshot_to: Feature snapshot for the later date.
        date_from: ISO date string for the earlier snapshot.
        date_to: ISO date string for the later snapshot.

    Returns:
        FeatureDriftResult with per-feature drift evidence and overall health status.
    """
    numeric_cols = [
        col for col in snapshot_from.select_dtypes(include="number").columns
        if col not in _SKIP_COLUMNS
    ]

    drifted: list[dict[str, Any]] = []

    for col in numeric_cols:
        if col not in snapshot_to.columns:
            continue
        s_from = snapshot_from[col].dropna()
        s_to = snapshot_to[col].dropna()
        if s_from.empty or s_to.empty:
            continue

        zero_rate_from = _zero_rate(s_from)
        zero_rate_to = _zero_rate(s_to)
        zero_rate_delta = abs(zero_rate_to - zero_rate_from)

        mean_from = float(s_from.mean())
        mean_to = float(s_to.mean())
        mean_rel = _relative_change(mean_from, mean_to)

        std_from = float(s_from.std())
        std_to = float(s_to.std())
        std_rel = _relative_change(std_from, std_to)

        is_drifted = (
            zero_rate_delta >= ZERO_RATE_ABS_DELTA_THRESHOLD
            or mean_rel >= MEAN_REL_CHANGE_THRESHOLD
            or std_rel >= STD_REL_CHANGE_THRESHOLD
        )

        if is_drifted:
            drifted.append({
                "feature": col,
                "zero_rate_from": round(zero_rate_from, 4),
                "zero_rate_to": round(zero_rate_to, 4),
                "zero_rate_delta": round(zero_rate_delta, 4),
                "mean_from": round(mean_from, 4),
                "mean_to": round(mean_to, 4),
                "mean_rel_change": round(mean_rel, 4),
                "std_from": round(std_from, 4),
                "std_to": round(std_to, 4),
                "std_rel_change": round(std_rel, 4),
            })

    return FeatureDriftResult(
        snapshot_from=date_from,
        snapshot_to=date_to,
        drifted_features=drifted,
        total_checked=len(numeric_cols),
        total_drifted=len(drifted),
        health_ok=len(drifted) == 0,
    )


def run_drift_check(db_path: str | None = None) -> FeatureDriftResult:
    """Load the two most recent feature snapshots and run drift detection.

    Returns:
        FeatureDriftResult. If fewer than two snapshots exist, returns a
        trivially healthy result.
    """
    settings = load_settings()
    store = DuckDBStore(db_path or settings.db_path)
    snapshot_dates = store.fetch_df(
        """
        SELECT DISTINCT snapshot_date
        FROM features.feature_snapshots_user_30d
        WHERE snapshot_date IS NOT NULL
        ORDER BY snapshot_date
        """
    )
    if snapshot_dates.empty:
        logger.warning("No feature snapshots found; skipping drift check")
        return FeatureDriftResult(
            snapshot_from="",
            snapshot_to="",
            drifted_features=[],
            total_checked=0,
            total_drifted=0,
            health_ok=True,
        )

    dates = sorted(pd.to_datetime(snapshot_dates["snapshot_date"]).unique())
    if len(dates) < 2:
        logger.info("Only one snapshot date available; skipping drift check")
        return FeatureDriftResult(
            snapshot_from=str(dates[0].date()) if dates else "",
            snapshot_to="",
            drifted_features=[],
            total_checked=0,
            total_drifted=0,
            health_ok=True,
        )

    date_from, date_to = dates[-2], dates[-1]
    cache_path = _drift_cache_path(settings)
    cached = _load_cached_result(cache_path, str(date_from.date()), str(date_to.date()))
    if cached is not None:
        return cached

    df_from = store.fetch_df(
        "SELECT * FROM features.feature_snapshots_user_30d WHERE snapshot_date = ?",
        (date_from.date(),),
    )
    df_to = store.fetch_df(
        "SELECT * FROM features.feature_snapshots_user_30d WHERE snapshot_date = ?",
        (date_to.date(),),
    )
    df_from["snapshot_date"] = pd.to_datetime(df_from["snapshot_date"])
    df_to["snapshot_date"] = pd.to_datetime(df_to["snapshot_date"])

    result = detect_drift(df_from, df_to, str(date_from.date()), str(date_to.date()))
    _write_cached_result(cache_path, result)

    if result.total_drifted > 0:
        logger.warning(
            "Feature drift detected: %d/%d features drifted between %s and %s",
            result.total_drifted,
            result.total_checked,
            result.snapshot_from,
            result.snapshot_to,
        )
        for feat in result.drifted_features[:5]:
            logger.warning("  Drifted feature: %s | mean_rel=%.2f | zero_rate_delta=%.2f",
                           feat["feature"], feat["mean_rel_change"], feat["zero_rate_delta"])
    else:
        logger.info(
            "Drift check OK: %d features checked, 0 drifted (%s → %s)",
            result.total_checked,
            result.snapshot_from,
            result.snapshot_to,
        )

    return result


# ── Score distribution monitoring (PSI) ───────────────────────────────────────

# PSI thresholds: < 0.10 = no shift, 0.10-0.25 = moderate, > 0.25 = severe
PSI_MODERATE_THRESHOLD = 0.10
PSI_SEVERE_THRESHOLD = 0.25
_PSI_BINS = 10  # number of equal-width quantile bins for PSI computation


@dataclass
class ScoreDriftResult:
    """PSI-based score distribution drift between two scoring runs."""
    run_from: str  # ISO timestamp of reference scoring run
    run_to: str    # ISO timestamp of current scoring run
    psi: float
    psi_severity: str  # "ok", "moderate", "severe"
    percentiles_from: dict[str, float]  # p10, p25, p50, p75, p90, p95, p99
    percentiles_to: dict[str, float]
    n_users_from: int
    n_users_to: int
    health_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def compute_psi(reference: np.ndarray, current: np.ndarray, n_bins: int = _PSI_BINS) -> float:
    """Compute Population Stability Index between two score arrays.

    Uses quantile-based bins derived from the reference distribution to ensure
    each reference bin contains ~equal probability mass. Clips to avoid log(0).

    PSI = Σ (current% - reference%) × ln(current% / reference%)

    Args:
        reference: Score array from the reference (older) scoring run.
        current: Score array from the current (newer) scoring run.
        n_bins: Number of bins. Default 10.

    Returns:
        PSI value. < 0.10 = stable, 0.10-0.25 = moderate, > 0.25 = severe.
    """
    if len(reference) == 0 or len(current) == 0:
        return 0.0
    # Build bin edges from reference quantiles (ensures equal mass bins)
    quantiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.unique(np.percentile(reference, quantiles))
    # Need at least 2 unique edges to bin
    if len(bin_edges) < 2:
        return 0.0
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    cur_counts, _ = np.histogram(current, bins=bin_edges)

    ref_pct = (ref_counts + 1e-6) / (len(reference) + 1e-6 * n_bins)
    cur_pct = (cur_counts + 1e-6) / (len(current) + 1e-6 * n_bins)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(0.0, psi)


def _score_psi_severity(psi: float) -> str:
    if psi >= PSI_SEVERE_THRESHOLD:
        return "severe"
    if psi >= PSI_MODERATE_THRESHOLD:
        return "moderate"
    return "ok"


def _score_percentiles(scores: np.ndarray) -> dict[str, float]:
    if len(scores) == 0:
        return {p: 0.0 for p in ("p10", "p25", "p50", "p75", "p90", "p95", "p99")}
    pcts = np.percentile(scores, [10, 25, 50, 75, 90, 95, 99])
    return dict(zip(("p10", "p25", "p50", "p75", "p90", "p95", "p99"), pcts.round(4).tolist()))


def detect_score_drift(
    scores_from: np.ndarray,
    scores_to: np.ndarray,
    run_from: str,
    run_to: str,
) -> ScoreDriftResult:
    """Compute PSI between two model score distributions.

    Args:
        scores_from: Score array from the reference run.
        scores_to: Score array from the current run.
        run_from: Human-readable label for the reference run (e.g. ISO timestamp).
        run_to: Human-readable label for the current run.

    Returns:
        ScoreDriftResult with PSI, severity, and percentile snapshots.
    """
    psi = compute_psi(scores_from, scores_to)
    severity = _score_psi_severity(psi)
    result = ScoreDriftResult(
        run_from=run_from,
        run_to=run_to,
        psi=round(psi, 4),
        psi_severity=severity,
        percentiles_from=_score_percentiles(scores_from),
        percentiles_to=_score_percentiles(scores_to),
        n_users_from=len(scores_from),
        n_users_to=len(scores_to),
        health_ok=(severity == "ok"),
    )
    if severity != "ok":
        logger.warning(
            "Score distribution drift detected: PSI=%.4f (%s) from %s → %s "
            "(p50: %.3f → %.3f, p95: %.3f → %.3f)",
            psi, severity, run_from, run_to,
            result.percentiles_from["p50"], result.percentiles_to["p50"],
            result.percentiles_from["p95"], result.percentiles_to["p95"],
        )
    else:
        logger.info(
            "Score distribution stable: PSI=%.4f from %s → %s (p50: %.3f → %.3f)",
            psi, run_from, run_to,
            result.percentiles_from["p50"], result.percentiles_to["p50"],
        )
    return result


def run_score_drift_check(db_path: str | None = None) -> ScoreDriftResult | None:
    """Compare the two most recent model prediction score distributions via PSI.

    Loads model_score from ops.model_predictions for the two most recent
    scoring run timestamps and computes PSI.

    Returns:
        ScoreDriftResult, or None if fewer than two scoring runs exist.
    """
    settings = load_settings()
    store = DuckDBStore(db_path or settings.db_path)
    try:
        run_dates = store.fetch_df(
            """
            SELECT DISTINCT scored_at
            FROM ops.model_predictions
            WHERE model_score IS NOT NULL
            ORDER BY scored_at DESC
            LIMIT 2
            """
        )
    except Exception:
        logger.debug("Could not query ops.model_predictions for score drift check")
        return None

    if len(run_dates) < 2:
        logger.info("Fewer than 2 scoring runs available; skipping score drift check")
        return None

    ts_to, ts_from = run_dates["scored_at"].iloc[0], run_dates["scored_at"].iloc[1]

    scores_from_df = store.fetch_df(
        "SELECT model_score FROM ops.model_predictions WHERE scored_at = ?", (ts_from,)
    )
    scores_to_df = store.fetch_df(
        "SELECT model_score FROM ops.model_predictions WHERE scored_at = ?", (ts_to,)
    )
    scores_from = scores_from_df["model_score"].dropna().to_numpy(dtype=float)
    scores_to = scores_to_df["model_score"].dropna().to_numpy(dtype=float)

    return detect_score_drift(scores_from, scores_to, str(ts_from), str(ts_to))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_drift_check()
    print(result.to_json())
    score_drift = run_score_drift_check()
    if score_drift is not None:
        print(score_drift.to_json())
