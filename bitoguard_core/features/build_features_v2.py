# bitoguard_core/features/build_features_v2.py
"""CLI entry-point: loads canonical tables, runs registry, stores v2 features."""
from __future__ import annotations
import os
import pandas as pd
from config import load_settings
from db.store import DuckDBStore
from features.registry import build_and_store_v2_features


def build_v2() -> None:
    settings = load_settings()
    store    = DuckDBStore(settings.db_path)
    export   = os.environ.get("EXPORT_TO_S3", "").lower() == "true"

    users   = store.read_table("canonical.users")
    fiat    = store.read_table("canonical.fiat_transactions")
    crypto  = store.read_table("canonical.crypto_transactions")
    trades  = store.read_table("canonical.trade_orders")
    logins  = store.read_table("canonical.login_events")
    edges   = store.read_table("canonical.entity_edges")

    # Anchor snapshot_date to the max of fiat/crypto transaction dates so that
    # 7d/30d rolling windows are computed relative to the latest observed transaction.
    # Trade/login events may have later timestamps (bot activity, session pings)
    # so they are excluded from this anchor — they don't represent financial events.
    # Without this fix, all short-horizon features are zero when data is archival.
    ts_maxes = []
    for df in (fiat, crypto):
        if df is not None and not df.empty and "occurred_at" in df.columns:
            ts_maxes.append(pd.to_datetime(df["occurred_at"], utc=True).max())
    snapshot_date = max(ts_maxes).normalize() if ts_maxes else None
    if snapshot_date is not None:
        print(f"[features-v2] anchoring snapshot_date to fiat/crypto max: {snapshot_date.date()}")

    result = build_and_store_v2_features(
        users, fiat, crypto, trades, logins, edges,
        snapshot_date=snapshot_date,
        store=store, export_to_s3=export,
    )
    print(f"[features-v2] {len(result)} users, {len(result.columns)} columns")


if __name__ == "__main__":
    build_v2()
