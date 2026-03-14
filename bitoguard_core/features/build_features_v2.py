# bitoguard_core/features/build_features_v2.py
"""CLI entry-point: loads canonical tables, runs registry, stores v2 features."""
from __future__ import annotations
from config import load_settings
from db.store import DuckDBStore
from features.registry import build_and_store_v2_features


def build_v2() -> None:
    settings = load_settings()
    store    = DuckDBStore(settings.db_path)

    users   = store.read_table("canonical.users")
    fiat    = store.read_table("canonical.fiat_transactions")
    crypto  = store.read_table("canonical.crypto_transactions")
    trades  = store.read_table("canonical.trade_orders")
    logins  = store.read_table("canonical.login_events")
    edges   = store.read_table("canonical.entity_edges")

    result = build_and_store_v2_features(users, fiat, crypto, trades, logins, edges, store=store)
    print(f"[features-v2] {len(result)} users, {len(result.columns)} columns")


if __name__ == "__main__":
    build_v2()
