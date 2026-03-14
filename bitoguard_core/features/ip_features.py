# bitoguard_core/features/ip_features.py
"""Per-user IP diversity from canonical.login_events.

IP events in this codebase are synthetic: each fiat/crypto/trade transaction
with a source_ip_hash produces one login_event with ip_address=source_ip_hash.
This gives per-transaction IP coverage, not real authentication events.
"""
from __future__ import annotations
import pandas as pd

NIGHT_HOURS = frozenset(range(22, 24))


def compute_ip_features(login_events: pd.DataFrame) -> pd.DataFrame:
    """4 per-user IP diversity features from canonical.login_events."""
    if login_events.empty or "ip_address" not in login_events.columns:
        return pd.DataFrame()

    df = login_events.copy()
    df["occurred_at"] = pd.to_datetime(df["occurred_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["user_id", "ip_address", "occurred_at"])

    rows = []
    for uid, grp in df.groupby("user_id"):
        counts = grp["ip_address"].value_counts(normalize=True)
        rows.append({
            "user_id":          uid,
            "unique_ips":       int(grp["ip_address"].nunique()),
            "ip_event_count":   int(len(grp)),
            "ip_concentration": float(counts.iloc[0]) if not counts.empty else 0.0,
            "ip_night_share":   float((grp["occurred_at"].dt.hour.isin(NIGHT_HOURS)).mean()),
        })

    return pd.DataFrame(rows).reset_index(drop=True)
