"""Build per-user event sequences from raw event tables.

Returns a dict: {user_id: (event_types, features, length)}
  event_types: np.ndarray int64 of shape (length,) — event type IDs
  features:    np.ndarray float32 of shape (length, 7) — continuous features
  length:      int — actual sequence length
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path

MAX_SEQ_LEN = 200  # 99.9% users have ≤200 events

EVENT_TYPES = {
    "twd_deposit": 0, "twd_withdrawal": 1,
    "crypto_deposit_internal": 2, "crypto_deposit_external": 3,
    "crypto_withdrawal_internal": 4, "crypto_withdrawal_external": 5,
    "swap_buy": 6, "swap_sell": 7,
    "trade_buy": 8, "trade_sell": 9,
}


def build_event_sequences(data_dir: str | Path) -> dict:
    """Load raw events, unify schema, build per-user padded sequences."""
    data_dir = Path(data_dir)

    twd = pd.read_parquet(data_dir / "twd_transfer.parquet")
    crypto = pd.read_parquet(data_dir / "crypto_transfer.parquet")
    swap = pd.read_parquet(data_dir / "usdt_swap.parquet")
    trade = pd.read_parquet(data_dir / "usdt_twd_trading.parquet")

    rows = []

    # TWD transfers
    df = twd.copy()
    df["event_type"] = df["is_deposit"].map({True: "twd_deposit", False: "twd_withdrawal"})
    if "is_deposit" not in df.columns:
        df["event_type"] = df["kind_label"].str.lower().map(
            lambda x: "twd_deposit" if "deposit" in str(x) else "twd_withdrawal")
    df["amount_twd"] = pd.to_numeric(df.get("amount_twd", df.get("amount", pd.Series(0))), errors="coerce").fillna(0).abs()
    df["timestamp"] = pd.to_datetime(df["created_at"], utc=True)
    df["ip_hash"] = df.get("source_ip_hash", pd.Series("", index=df.index)).fillna("")
    rows.append(df[["user_id", "timestamp", "event_type", "amount_twd", "ip_hash"]])

    # Crypto transfers
    df = crypto.copy()
    kind = df.get("kind_label", pd.Series("deposit", index=df.index)).fillna("deposit").str.lower()
    internal = df.get("is_internal_transfer", pd.Series(False, index=df.index)).fillna(False)
    deposit_mask = kind.str.contains("deposit", na=False)
    internal_mask = internal.astype(bool)
    df["event_type"] = "crypto_withdrawal_external"
    df.loc[deposit_mask & internal_mask, "event_type"] = "crypto_deposit_internal"
    df.loc[deposit_mask & ~internal_mask, "event_type"] = "crypto_deposit_external"
    df.loc[~deposit_mask & internal_mask, "event_type"] = "crypto_withdrawal_internal"
    df["amount_twd"] = pd.to_numeric(df.get("amount_twd_equiv", df.get("amount_twd", pd.Series(0))), errors="coerce").fillna(0).abs()
    df["timestamp"] = pd.to_datetime(df["created_at"], utc=True)
    df["ip_hash"] = df.get("source_ip_hash", pd.Series("", index=df.index)).fillna("")
    rows.append(df[["user_id", "timestamp", "event_type", "amount_twd", "ip_hash"]])

    # USDT swaps
    df = swap.copy()
    kind = df.get("kind_label", pd.Series("buy", index=df.index)).fillna("buy").str.lower()
    df["event_type"] = kind.map(lambda x: "swap_buy" if "buy" in str(x) else "swap_sell")
    df["amount_twd"] = pd.to_numeric(df.get("twd_amount", df.get("amount_twd", pd.Series(0))), errors="coerce").fillna(0).abs()
    df["timestamp"] = pd.to_datetime(df["created_at"], utc=True)
    df["ip_hash"] = ""
    rows.append(df[["user_id", "timestamp", "event_type", "amount_twd", "ip_hash"]])

    # USDT/TWD trading
    df = trade.copy()
    if "is_buy" in df.columns:
        df["event_type"] = df["is_buy"].map({True: "trade_buy", False: "trade_sell"})
    else:
        side = df.get("side_label", pd.Series("buy", index=df.index)).fillna("buy").str.lower()
        df["event_type"] = side.map(lambda x: "trade_buy" if "buy" in str(x) else "trade_sell")
    df["amount_twd"] = pd.to_numeric(df.get("trade_notional_twd", df.get("amount_twd", pd.Series(0))), errors="coerce").fillna(0).abs()
    ts_col = "updated_at" if "updated_at" in df.columns else "created_at"
    df["timestamp"] = pd.to_datetime(df[ts_col], utc=True)
    df["ip_hash"] = df.get("source_ip_hash", pd.Series("", index=df.index)).fillna("")
    rows.append(df[["user_id", "timestamp", "event_type", "amount_twd", "ip_hash"]])

    all_events = pd.concat(rows, ignore_index=True)
    all_events = all_events.sort_values(["user_id", "timestamp"]).reset_index(drop=True)
    all_events["type_id"] = all_events["event_type"].map(EVENT_TYPES).fillna(0).astype(int)
    all_events["log_amount"] = np.log1p(all_events["amount_twd"])

    all_events["local_hour"] = all_events["timestamp"].dt.tz_convert("Asia/Taipei").dt.hour
    all_events["is_night"] = ((all_events["local_hour"] >= 23) | (all_events["local_hour"] < 5)).astype(float)
    all_events["is_weekend"] = all_events["timestamp"].dt.dayofweek.isin([5, 6]).astype(float)
    all_events["hour_norm"] = all_events["local_hour"] / 23.0

    sequences = {}
    for uid, grp in all_events.groupby("user_id"):
        grp = grp.head(MAX_SEQ_LEN)
        n = len(grp)

        type_ids = grp["type_id"].values
        amounts = grp["log_amount"].values

        ts = grp["timestamp"].values.astype("datetime64[s]").astype(float)
        deltas = np.zeros(n)
        if n > 1:
            deltas[1:] = np.clip((ts[1:] - ts[:-1]) / 3600.0, 0, 8760)

        ips = grp["ip_hash"].fillna("").values
        ip_changed = np.zeros(n)
        if n > 1:
            ip_changed[1:] = (ips[1:] != ips[:-1]).astype(float)

        ranks = pd.Series(amounts).rank(pct=True).values

        features = np.stack([
            amounts,
            np.clip(deltas / 720.0, 0, 1),
            grp["hour_norm"].values,
            grp["is_night"].values,
            grp["is_weekend"].values,
            ip_changed,
            ranks,
        ], axis=1).astype(np.float32)

        sequences[int(uid)] = (type_ids.astype(np.int64), features, n)

    print(f"[event_sequence] Built sequences for {len(sequences)} users, "
          f"total {sum(s[2] for s in sequences.values())} events")
    return sequences
