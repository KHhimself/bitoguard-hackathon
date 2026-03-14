# bitoguard_core/tests/test_feature_modules.py
from __future__ import annotations
import pandas as pd
import pytest
from features.profile_features import compute_profile_features


def _users_df():
    return pd.DataFrame([{
        "user_id": "u1",
        "created_at": "2025-01-01T00:00:00+08:00",
        "kyc_level": "level2",
        "occupation": "career_1",
        "monthly_income_twd": 50000.0,
        "declared_source_of_funds": "income_source_2",
        "activity_window": "web",
    }])


def test_profile_features_columns():
    result = compute_profile_features(_users_df())
    assert "user_id" in result.columns
    assert "kyc_level_code" in result.columns
    assert "account_age_days" in result.columns
    assert "occupation_code" in result.columns
    assert len(result) == 1


def test_profile_features_kyc_level2():
    result = compute_profile_features(_users_df())
    assert result.iloc[0]["kyc_level_code"] == 2


def test_profile_features_empty():
    result = compute_profile_features(pd.DataFrame(columns=_users_df().columns))
    assert len(result) == 0


from features.twd_features import compute_twd_features, _gap_stats, _agg_stats


def _fiat_df():
    return pd.DataFrame([
        {"user_id": "u1", "occurred_at": "2025-01-01T01:00:00+00:00", "direction": "deposit",    "amount_twd": 10000.0},
        {"user_id": "u1", "occurred_at": "2025-01-01T02:00:00+00:00", "direction": "deposit",    "amount_twd": 20000.0},
        {"user_id": "u1", "occurred_at": "2025-01-02T03:00:00+00:00", "direction": "withdrawal", "amount_twd": 5000.0},
        {"user_id": "u2", "occurred_at": "2025-01-05T10:00:00+00:00", "direction": "deposit",    "amount_twd": 100.0},
    ])


def test_twd_features_columns():
    result = compute_twd_features(_fiat_df())
    for col in ["twd_all_count", "twd_dep_count", "twd_wdr_count",
                "twd_net_flow", "twd_night_share",
                "twd_dep_gap_min", "twd_dep_rapid_1h_share"]:
        assert col in result.columns, f"missing {col}"


def test_twd_features_u1_counts():
    result = compute_twd_features(_fiat_df())
    u1 = result[result["user_id"] == "u1"].iloc[0]
    assert u1["twd_all_count"] == 3
    assert u1["twd_dep_count"] == 2
    assert u1["twd_wdr_count"] == 1
    assert u1["twd_net_flow"] == pytest.approx(30000.0 - 5000.0)


def test_twd_features_gap():
    result = compute_twd_features(_fiat_df())
    u1 = result[result["user_id"] == "u1"].iloc[0]
    # Two deposits 1h apart → gap_min ≈ 60 minutes
    assert u1["twd_dep_gap_min"] == pytest.approx(60.0, abs=5.0)
