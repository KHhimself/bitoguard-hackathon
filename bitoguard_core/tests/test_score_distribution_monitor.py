"""Tests for PSI-based score distribution monitoring (MONITORING-002).

Verifies that the score drift detection:
- Returns 'ok' for identical distributions
- Returns 'moderate' for mild distributional shift
- Returns 'severe' for large shift (regime change)
- Handles edge cases: empty arrays, single-value distributions
"""
from __future__ import annotations

import numpy as np
import pytest

from services.drift import (
    PSI_MODERATE_THRESHOLD,
    PSI_SEVERE_THRESHOLD,
    ScoreDriftResult,
    compute_psi,
    detect_score_drift,
)


class TestComputePsi:
    def test_identical_distributions_psi_near_zero(self):
        rng = np.random.default_rng(42)
        scores = rng.beta(1.5, 10.0, size=5000)
        psi = compute_psi(scores, scores.copy())
        assert psi < 0.01, f"Identical distributions should have PSI ≈ 0, got {psi}"

    def test_similar_distributions_psi_ok(self):
        rng = np.random.default_rng(0)
        ref = rng.beta(1.5, 10.0, size=5000)
        cur = rng.beta(1.6, 10.5, size=5000)  # slight shift
        psi = compute_psi(ref, cur)
        assert psi < PSI_MODERATE_THRESHOLD, f"Similar distributions should be ok, got PSI={psi}"

    def test_large_shift_psi_severe(self):
        rng = np.random.default_rng(1)
        ref = rng.beta(0.5, 10.0, size=5000)   # very low scores
        cur = rng.beta(5.0, 3.0, size=5000)    # high scores — regime change
        psi = compute_psi(ref, cur)
        assert psi >= PSI_SEVERE_THRESHOLD, f"Severe shift should trigger PSI ≥ {PSI_SEVERE_THRESHOLD}, got {psi}"

    def test_large_shift_psi_above_moderate(self):
        # beta(1,10) mean≈0.09 vs beta(2,8) mean≈0.20 — large shift, PSI well above moderate
        rng = np.random.default_rng(2)
        ref = rng.beta(1.0, 10.0, size=10000)
        cur = rng.beta(2.0, 8.0, size=10000)
        psi = compute_psi(ref, cur)
        assert psi >= PSI_MODERATE_THRESHOLD, f"Large shift should trigger PSI ≥ moderate, got {psi}"

    def test_empty_reference_returns_zero(self):
        cur = np.array([0.1, 0.2, 0.3])
        psi = compute_psi(np.array([]), cur)
        assert psi == 0.0

    def test_empty_current_returns_zero(self):
        ref = np.array([0.1, 0.2, 0.3])
        psi = compute_psi(ref, np.array([]))
        assert psi == 0.0

    def test_constant_distribution_does_not_raise(self):
        # All scores identical → single unique bin edge
        ref = np.full(100, 0.5)
        cur = np.full(100, 0.5)
        psi = compute_psi(ref, cur)
        assert psi >= 0.0  # Must not raise

    def test_psi_non_negative(self):
        rng = np.random.default_rng(99)
        for _ in range(20):
            a = rng.uniform(0, 1, 1000)
            b = rng.uniform(0, 1, 1000)
            assert compute_psi(a, b) >= 0.0


class TestDetectScoreDrift:
    def _make_drift_result(self, psi_expected_severity: str) -> ScoreDriftResult:
        rng = np.random.default_rng(7)
        if psi_expected_severity == "ok":
            ref = rng.beta(1.5, 10.0, size=5000)
            cur = rng.beta(1.5, 10.0, size=5000)
        elif psi_expected_severity == "severe":
            ref = rng.beta(0.5, 15.0, size=5000)
            cur = rng.beta(5.0, 2.0, size=5000)
        else:
            ref = rng.beta(1.0, 10.0, size=5000)
            cur = rng.beta(2.5, 7.0, size=5000)
        return detect_score_drift(ref, cur, "2026-01-01", "2026-01-02")

    def test_ok_severity_health_ok(self):
        result = self._make_drift_result("ok")
        assert result.health_ok is True
        assert result.psi_severity == "ok"
        assert result.psi >= 0.0

    def test_severe_shift_health_not_ok(self):
        result = self._make_drift_result("severe")
        assert result.health_ok is False
        assert result.psi_severity == "severe"
        assert result.psi >= PSI_SEVERE_THRESHOLD

    def test_result_has_percentiles(self):
        rng = np.random.default_rng(3)
        scores = rng.beta(1.5, 10.0, size=1000)
        result = detect_score_drift(scores, scores.copy(), "t0", "t1")
        for key in ("p10", "p25", "p50", "p75", "p90", "p95", "p99"):
            assert key in result.percentiles_from
            assert key in result.percentiles_to

    def test_result_n_users_correct(self):
        rng = np.random.default_rng(4)
        ref = rng.uniform(0, 1, 200)
        cur = rng.uniform(0, 1, 300)
        result = detect_score_drift(ref, cur, "r", "c")
        assert result.n_users_from == 200
        assert result.n_users_to == 300

    def test_to_json_round_trips(self):
        import json
        rng = np.random.default_rng(5)
        scores = rng.beta(1.5, 10.0, size=500)
        result = detect_score_drift(scores, scores.copy(), "a", "b")
        payload = json.loads(result.to_json())
        assert payload["psi_severity"] == "ok"
        assert "p50" in payload["percentiles_from"]
