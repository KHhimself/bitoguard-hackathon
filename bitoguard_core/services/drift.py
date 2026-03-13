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
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

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

    snapshots = store.read_table("features.feature_snapshots_user_30d")
    if snapshots.empty or "snapshot_date" not in snapshots.columns:
        logger.warning("No feature snapshots found; skipping drift check")
        return FeatureDriftResult(
            snapshot_from="",
            snapshot_to="",
            drifted_features=[],
            total_checked=0,
            total_drifted=0,
            health_ok=True,
        )

    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    dates = sorted(snapshots["snapshot_date"].unique())
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
    df_from = snapshots[snapshots["snapshot_date"] == date_from]
    df_to = snapshots[snapshots["snapshot_date"] == date_to]

    result = detect_drift(df_from, df_to, str(date_from.date()), str(date_to.date()))

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_drift_check()
    print(result.to_json())
