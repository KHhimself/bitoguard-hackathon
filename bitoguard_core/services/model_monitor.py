"""Model health monitoring service (MONITORING-003).

Tracks:
  1. Model staleness — warns when the model bundle is older than a configured
     threshold, indicating the model may no longer reflect current user behaviour.
  2. Score distribution sanity — validates that predict-only scores fall within
     historically observed percentile ranges (catches serialization bugs or
     upstream data schema changes).

Staleness thresholds (configurable via env vars):
  BITOGUARD_MODEL_STALENESS_WARN_DAYS  default=30   → WARNING log
  BITOGUARD_MODEL_STALENESS_ERROR_DAYS default=90   → ERROR log + health_ok=False
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Defaults; override via environment variables
_DEFAULT_WARN_DAYS = int(os.environ.get("BITOGUARD_MODEL_STALENESS_WARN_DAYS", "30"))
_DEFAULT_ERROR_DAYS = int(os.environ.get("BITOGUARD_MODEL_STALENESS_ERROR_DAYS", "90"))

# Regex to extract ISO timestamp from bundle_version strings like
# "official_bundle_20260319T040130Z" or "transductive_v1_20260319T040130Z"
_BUNDLE_VERSION_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


@dataclass
class ModelStalenessResult:
    bundle_version: str
    trained_at: str | None       # ISO timestamp extracted from bundle_version
    age_days: float | None       # days since training; None if unparseable
    staleness_level: str         # "ok", "warn", "error"
    warn_threshold_days: int
    error_threshold_days: int
    health_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def check_model_staleness(
    bundle_path: str | Path,
    warn_days: int = _DEFAULT_WARN_DAYS,
    error_days: int = _DEFAULT_ERROR_DAYS,
    now: datetime | None = None,
) -> ModelStalenessResult:
    """Check if the model bundle is stale based on its training timestamp.

    The training time is extracted from the ``bundle_version`` field, which
    encodes the timestamp as ``<prefix>_<YYYYMMDDTHHMMSSZ>``.

    Args:
        bundle_path: Path to the ``official_bundle.json`` or compatible bundle.
        warn_days: Days after which to emit a WARNING.
        error_days: Days after which to emit an ERROR and set health_ok=False.
        now: Reference "current" time (UTC). Defaults to ``datetime.now(UTC)``.

    Returns:
        ModelStalenessResult with age_days and staleness_level.
    """
    bundle_path = Path(bundle_path)
    if not bundle_path.exists():
        logger.warning("Bundle file not found: %s", bundle_path)
        return ModelStalenessResult(
            bundle_version="<not found>",
            trained_at=None,
            age_days=None,
            staleness_level="error",
            warn_threshold_days=warn_days,
            error_threshold_days=error_days,
            health_ok=False,
        )

    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse bundle file %s: %s", bundle_path, exc)
        return ModelStalenessResult(
            bundle_version="<parse error>",
            trained_at=None,
            age_days=None,
            staleness_level="error",
            warn_threshold_days=warn_days,
            error_threshold_days=error_days,
            health_ok=False,
        )

    bundle_version = bundle.get("bundle_version", "")
    trained_at: str | None = None
    age_days: float | None = None

    match = _BUNDLE_VERSION_TS_RE.search(bundle_version)
    if match:
        ts_str = match.group(1)
        try:
            trained_dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            trained_at = trained_dt.isoformat()
            reference = now if now is not None else datetime.now(timezone.utc)
            age_days = (reference - trained_dt).total_seconds() / 86400.0
        except ValueError:
            pass

    if age_days is None:
        staleness_level = "ok"  # Cannot determine age → non-blocking
        health_ok = True
        logger.info("Model staleness: could not parse training timestamp from '%s'", bundle_version)
    elif age_days >= error_days:
        staleness_level = "error"
        health_ok = False
        logger.error(
            "Model is stale: %.1f days old (error threshold: %d days). "
            "Retrain required. Bundle: %s",
            age_days, error_days, bundle_version,
        )
    elif age_days >= warn_days:
        staleness_level = "warn"
        health_ok = True
        logger.warning(
            "Model is ageing: %.1f days old (warn threshold: %d days). "
            "Consider scheduling a retrain. Bundle: %s",
            age_days, warn_days, bundle_version,
        )
    else:
        staleness_level = "ok"
        health_ok = True
        logger.debug("Model freshness OK: %.1f days old. Bundle: %s", age_days, bundle_version)

    return ModelStalenessResult(
        bundle_version=bundle_version,
        trained_at=trained_at,
        age_days=round(age_days, 2) if age_days is not None else None,
        staleness_level=staleness_level,
        warn_threshold_days=warn_days,
        error_threshold_days=error_days,
        health_ok=health_ok,
    )


@dataclass
class ScoreSanityResult:
    """Validates that score distribution percentiles fall within expected ranges."""
    n_scores: int
    p50: float
    p95: float
    p99: float
    checks_passed: list[str]
    checks_failed: list[str]
    health_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# Historical score distribution bounds (derived from v46, across labeled + predict_only)
# The predict_only cohort is heavily negatives → p50 can be as low as 0.003.
# Bounds are deliberately wide to catch degenerate outputs, not calibration shifts.
# p50 ≈ 0.001–0.25  (most users are negative; degenerate if p50 ≥ 0.25 or p50 ≈ 0)
# p95 ≈ 0.05–0.80   (top-5% should have elevated risk scores)
# p99 ≈ 0.15–0.99   (top-1% should be clearly flagged)
_SCORE_SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    "p50": (0.001, 0.25),
    "p95": (0.05, 0.80),
    "p99": (0.15, 0.99),
}


def check_score_sanity(scores: np.ndarray) -> ScoreSanityResult:
    """Validate that score distribution percentiles fall within expected bounds.

    Catches cases where the model is outputting degenerate scores (all near 0,
    all near 1, or inverted) due to serialization bugs or schema changes.

    Args:
        scores: Array of model scores in [0, 1].

    Returns:
        ScoreSanityResult with per-check pass/fail details.
    """
    if len(scores) == 0:
        return ScoreSanityResult(
            n_scores=0, p50=0.0, p95=0.0, p99=0.0,
            checks_passed=[], checks_failed=["no_scores"],
            health_ok=False,
        )

    p50, p95, p99 = np.percentile(scores, [50, 95, 99]).tolist()
    checks_passed: list[str] = []
    checks_failed: list[str] = []

    for name, (lo, hi) in _SCORE_SANITY_BOUNDS.items():
        val = {"p50": p50, "p95": p95, "p99": p99}[name]
        if lo <= val <= hi:
            checks_passed.append(f"{name}={val:.4f} in [{lo}, {hi}]")
        else:
            checks_failed.append(f"{name}={val:.4f} outside [{lo}, {hi}]")
            logger.warning(
                "Score sanity check FAILED: %s=%.4f outside expected [%.3f, %.3f]",
                name, val, lo, hi,
            )

    health_ok = len(checks_failed) == 0
    if health_ok:
        logger.info("Score sanity OK: p50=%.4f, p95=%.4f, p99=%.4f", p50, p95, p99)
    return ScoreSanityResult(
        n_scores=len(scores),
        p50=round(p50, 4),
        p95=round(p95, 4),
        p99=round(p99, 4),
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        health_ok=health_ok,
    )
