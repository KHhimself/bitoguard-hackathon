from __future__ import annotations

import pandas as pd


BEHAVIORAL_FEATURES = [
    "fiat_in_30d",
    "fiat_out_30d",
    "trade_notional_30d",
    "crypto_withdraw_30d",
    "trade_count_30d",
]


def dormancy_score(row: dict) -> float:
    total = sum(float(row.get(feature, 0.0) or 0.0) for feature in BEHAVIORAL_FEATURES)
    return 1.0 if total == 0.0 else 0.0


def dormancy_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    available = [feature for feature in BEHAVIORAL_FEATURES if feature in frame.columns]
    if not available:
        return pd.Series(0.0, index=frame.index, dtype=float)
    totals = frame[available].fillna(0.0).astype(float).sum(axis=1)
    return (totals == 0.0).astype(float)
