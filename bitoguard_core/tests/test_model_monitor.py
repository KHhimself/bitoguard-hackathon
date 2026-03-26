"""Tests for model staleness and score sanity monitoring (MONITORING-003)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from services.model_monitor import (
    ModelStalenessResult,
    ScoreSanityResult,
    check_model_staleness,
    check_score_sanity,
)


def _write_bundle(path: Path, bundle_version: str) -> None:
    path.write_text(json.dumps({"bundle_version": bundle_version}), encoding="utf-8")


class TestCheckModelStaleness:
    def _now(self) -> datetime:
        return datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_fresh_model_ok(self, tmp_path):
        # Bundle trained 5 days ago — should be "ok"
        _write_bundle(tmp_path / "bundle.json", "official_bundle_20260314T120000Z")
        result = check_model_staleness(tmp_path / "bundle.json", warn_days=30, error_days=90, now=self._now())
        assert result.staleness_level == "ok"
        assert result.health_ok is True
        assert result.age_days is not None
        assert 4.9 < result.age_days < 5.1

    def test_warn_threshold_triggered(self, tmp_path):
        # Bundle trained 40 days ago, warn=30
        _write_bundle(tmp_path / "bundle.json", "official_bundle_20260208T120000Z")
        result = check_model_staleness(tmp_path / "bundle.json", warn_days=30, error_days=90, now=self._now())
        assert result.staleness_level == "warn"
        assert result.health_ok is True  # warn is non-blocking

    def test_error_threshold_triggered(self, tmp_path):
        # Bundle trained 100 days ago, error=90
        _write_bundle(tmp_path / "bundle.json", "official_bundle_20251209T120000Z")
        result = check_model_staleness(tmp_path / "bundle.json", warn_days=30, error_days=90, now=self._now())
        assert result.staleness_level == "error"
        assert result.health_ok is False

    def test_missing_bundle_returns_error(self, tmp_path):
        result = check_model_staleness(tmp_path / "nonexistent.json")
        assert result.staleness_level == "error"
        assert result.health_ok is False
        assert result.bundle_version == "<not found>"

    def test_unparseable_bundle_version(self, tmp_path):
        _write_bundle(tmp_path / "bundle.json", "legacy_bundle_no_timestamp")
        result = check_model_staleness(tmp_path / "bundle.json", now=self._now())
        # Cannot determine age → non-blocking
        assert result.staleness_level == "ok"
        assert result.age_days is None
        assert result.health_ok is True

    def test_to_json_round_trips(self, tmp_path):
        _write_bundle(tmp_path / "bundle.json", "official_bundle_20260314T120000Z")
        result = check_model_staleness(tmp_path / "bundle.json", now=self._now())
        payload = json.loads(result.to_json())
        assert "staleness_level" in payload
        assert "age_days" in payload

    def test_transductive_bundle_format_parsed(self, tmp_path):
        _write_bundle(tmp_path / "bundle.json", "transductive_v1_20260310T040130Z")
        result = check_model_staleness(tmp_path / "bundle.json", warn_days=30, error_days=90, now=self._now())
        assert result.age_days is not None
        assert result.age_days > 0

    def test_real_bundle_not_stale(self):
        """Verify the actual v46 bundle is not critically stale."""
        bundle_path = Path("artifacts/official_bundle.json")
        if not bundle_path.exists():
            pytest.skip("official_bundle.json not available")
        result = check_model_staleness(bundle_path, error_days=365)  # 1 year for CI
        assert result.health_ok is True, f"Bundle stale: {result}"


class TestCheckScoreSanity:
    def test_typical_aml_scores_pass(self):
        # Realistic AML score distribution: 96.8% negatives → heavily left-skewed
        rng = np.random.default_rng(42)
        scores = np.concatenate([
            rng.beta(0.5, 8.0, size=49000),   # negatives: very low scores
            rng.beta(3.0, 2.0, size=1640),     # positives: higher scores
        ])
        result = check_score_sanity(scores)
        assert result.health_ok is True, f"Typical AML scores should pass sanity: {result.checks_failed}"

    def test_all_zero_scores_fails(self):
        # Model outputting all zeros (serialization bug)
        scores = np.zeros(10000)
        result = check_score_sanity(scores)
        assert result.health_ok is False

    def test_all_one_scores_fails(self):
        # Model outputting all ones (degenerate)
        scores = np.ones(10000)
        result = check_score_sanity(scores)
        assert result.health_ok is False

    def test_empty_scores_fail(self):
        result = check_score_sanity(np.array([]))
        assert result.health_ok is False
        assert "no_scores" in result.checks_failed

    def test_result_has_correct_percentile_keys(self):
        rng = np.random.default_rng(0)
        scores = rng.beta(0.5, 8.0, size=5000)
        result = check_score_sanity(scores)
        assert hasattr(result, "p50")
        assert hasattr(result, "p95")
        assert hasattr(result, "p99")
        assert 0 <= result.p50 <= 1
        assert 0 <= result.p95 <= 1
        assert 0 <= result.p99 <= 1

    def test_to_json_serializable(self):
        rng = np.random.default_rng(1)
        scores = rng.beta(0.5, 8.0, size=5000)
        result = check_score_sanity(scores)
        payload = json.loads(result.to_json())
        assert "health_ok" in payload
        assert "checks_passed" in payload
