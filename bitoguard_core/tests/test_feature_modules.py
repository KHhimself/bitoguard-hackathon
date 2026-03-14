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
