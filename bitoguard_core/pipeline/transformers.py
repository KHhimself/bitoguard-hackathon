"""BitoPro upstream schema → BitoGuard canonical schema transformation.

This module is the single authoritative place for converting raw PostgREST
API payloads into the canonical table structure used by the rest of the pipeline.
It contains no HTTP logic; all network I/O lives in source_client.py.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


PROTOCOL_LABELS = {
    0: "SELF",
    1: "ERC20",
    2: "OMNI",
    3: "BNB",
    4: "TRC20",
    5: "BSC",
    6: "POLYGON",
}

USER_SOURCE_LABELS = {
    0: "web",
    1: "app",
}

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


# ── Primitive coercions ───────────────────────────────────────────────────────

def parse_upstream_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


def format_source_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(TAIPEI_TZ).isoformat(timespec="seconds")


def scale_fixed_1e8(value: Any) -> float | None:
    """Scale an integer fixed-point value stored as N×10⁸ to a float."""
    if value in (None, ""):
        return None
    return float(value) / 1e8


def coerce_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


# ── User field derivation ─────────────────────────────────────────────────────

def derive_user_created_at(row: dict[str, Any]) -> datetime | None:
    candidates = [
        parse_upstream_datetime(row.get("level1_finished_at")),
        parse_upstream_datetime(row.get("confirmed_at")),
        parse_upstream_datetime(row.get("level2_finished_at")),
    ]
    available = [c for c in candidates if c is not None]
    return min(available) if available else None


def derive_kyc_level(row: dict[str, Any]) -> str | None:
    if row.get("level2_finished_at"):
        return "level2"
    if row.get("level1_finished_at"):
        return "level1"
    if row.get("confirmed_at"):
        return "email_verified"
    return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sort_rows(rows: list[dict[str, Any]], time_field: str, id_field: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            item.get(time_field) or "",
            item.get(id_field) or "",
        ),
    )


# ── Main projection ───────────────────────────────────────────────────────────

def project_postgrest_payload(payload: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Convert a raw PostgREST multi-table payload to BitoGuard canonical tables."""
    user_info = payload["user_info"]
    twd_transfer = payload["twd_transfer"]
    usdt_twd_trading = payload["usdt_twd_trading"]
    usdt_swap = payload["usdt_swap"]
    crypto_transfer = payload["crypto_transfer"]
    train_label = payload["train_label"]

    observed_activity: dict[str, list[datetime]] = defaultdict(list)

    fiat_transactions: list[dict[str, Any]] = []
    fiat_events_for_login: list[dict[str, Any]] = []
    for row in twd_transfer:
        user_id = str(row["user_id"])
        occurred_at = parse_upstream_datetime(row.get("created_at"))
        if occurred_at is None:
            continue
        observed_activity[user_id].append(occurred_at)
        fiat_transactions.append({
            "fiat_txn_id": f"twd_{row['id']}",
            "user_id": user_id,
            "occurred_at": format_source_datetime(occurred_at),
            "direction": "deposit" if coerce_int(row.get("kind"), 0) == 0 else "withdrawal",
            "amount_twd": scale_fixed_1e8(row.get("ori_samount")),
            "currency": "TWD",
            "bank_account_id": None,
            "method": "bank_transfer",
            "status": "completed",
        })
        if row.get("source_ip_hash"):
            fiat_events_for_login.append({
                "event_id": f"twd_{row['id']}",
                "user_id": user_id,
                "occurred_at": occurred_at,
                "ip_address": str(row["source_ip_hash"]),
                "app_channel": None,
            })

    trade_orders: list[dict[str, Any]] = []
    trade_events_for_login: list[dict[str, Any]] = []
    for row in usdt_twd_trading:
        user_id = str(row["user_id"])
        occurred_at = parse_upstream_datetime(row.get("updated_at"))
        if occurred_at is None:
            continue
        quantity = scale_fixed_1e8(row.get("trade_samount"))
        price_twd = scale_fixed_1e8(row.get("twd_srate"))
        observed_activity[user_id].append(occurred_at)
        trade_orders.append({
            "trade_id": f"book_{row['id']}",
            "user_id": user_id,
            "occurred_at": format_source_datetime(occurred_at),
            "side": "buy" if coerce_int(row.get("is_buy"), 0) == 1 else "sell",
            "base_asset": "USDT",
            "quote_asset": "TWD",
            "price_twd": price_twd,
            "quantity": quantity,
            "notional_twd": None if quantity is None or price_twd is None else quantity * price_twd,
            "fee_twd": 0.0,
            "order_type": "market" if coerce_int(row.get("is_market"), 0) == 1 else "limit",
            "status": "filled",
        })
        if row.get("source_ip_hash"):
            trade_events_for_login.append({
                "event_id": f"book_{row['id']}",
                "user_id": user_id,
                "occurred_at": occurred_at,
                "ip_address": str(row["source_ip_hash"]),
                "app_channel": USER_SOURCE_LABELS.get(coerce_int(row.get("source"), -1)),
            })

    for row in usdt_swap:
        user_id = str(row["user_id"])
        occurred_at = parse_upstream_datetime(row.get("created_at"))
        if occurred_at is None:
            continue
        quantity = scale_fixed_1e8(row.get("currency_samount"))
        notional_twd = scale_fixed_1e8(row.get("twd_samount"))
        observed_activity[user_id].append(occurred_at)
        trade_orders.append({
            "trade_id": f"swap_{row['id']}",
            "user_id": user_id,
            "occurred_at": format_source_datetime(occurred_at),
            "side": "buy" if coerce_int(row.get("kind"), 0) == 0 else "sell",
            "base_asset": "USDT",
            "quote_asset": "TWD",
            "price_twd": None if quantity in (None, 0) or notional_twd is None else notional_twd / quantity,
            "quantity": quantity,
            "notional_twd": notional_twd,
            "fee_twd": 0.0,
            "order_type": "instant_swap",
            "status": "filled",
        })

    crypto_transactions: list[dict[str, Any]] = []
    wallet_records: dict[str, dict[str, Any]] = {}
    crypto_events_for_login: list[dict[str, Any]] = []

    def upsert_wallet(
        wallet_id: str | None,
        *,
        user_id: str | None,
        asset: str | None,
        network: str | None,
        occurred_at: datetime,
        wallet_kind: str,
    ) -> None:
        if not wallet_id:
            return
        existing = wallet_records.get(wallet_id)
        if existing is None:
            wallet_records[wallet_id] = {
                "wallet_id": wallet_id,
                "wallet_kind": wallet_kind,
                "user_id": user_id,
                "asset": asset,
                "network": network,
                "created_at": format_source_datetime(occurred_at),
            }
            return
        if existing["user_id"] is None and user_id is not None:
            existing["user_id"] = user_id
        if existing["asset"] is None and asset is not None:
            existing["asset"] = asset
        if existing["network"] is None and network is not None:
            existing["network"] = network
        if existing["created_at"] is None or format_source_datetime(occurred_at) < existing["created_at"]:
            existing["created_at"] = format_source_datetime(occurred_at)

    for row in crypto_transfer:
        user_id = str(row["user_id"])
        occurred_at = parse_upstream_datetime(row.get("created_at"))
        if occurred_at is None:
            continue
        direction = "deposit" if coerce_int(row.get("kind"), 0) == 0 else "withdrawal"
        asset = str(row.get("currency")).upper() if row.get("currency") else None
        network = PROTOCOL_LABELS.get(coerce_int(row.get("protocol"), 0)) if row.get("protocol") not in (None, "") else None
        amount_asset = scale_fixed_1e8(row.get("ori_samount"))
        rate_twd = scale_fixed_1e8(row.get("twd_srate"))
        observed_activity[user_id].append(occurred_at)

        if direction == "deposit":
            wallet_id = str(row["to_wallet_hash"]) if row.get("to_wallet_hash") else None
            counterparty_wallet_id = str(row["from_wallet_hash"]) if row.get("from_wallet_hash") else None
        else:
            wallet_id = str(row["from_wallet_hash"]) if row.get("from_wallet_hash") else None
            counterparty_wallet_id = str(row["to_wallet_hash"]) if row.get("to_wallet_hash") else None

        counterparty_user_id = (
            str(row["relation_user_id"])
            if row.get("relation_user_id") not in (None, "")
            else None
        )
        upsert_wallet(wallet_id, user_id=user_id, asset=asset, network=network,
                      occurred_at=occurred_at, wallet_kind="observed_user_wallet")
        upsert_wallet(counterparty_wallet_id, user_id=counterparty_user_id, asset=asset,
                      network=network, occurred_at=occurred_at, wallet_kind="counterparty_wallet")

        crypto_transactions.append({
            "crypto_txn_id": f"crypto_{row['id']}",
            "user_id": user_id,
            "occurred_at": format_source_datetime(occurred_at),
            "direction": direction,
            "asset": asset,
            "network": network,
            "wallet_id": wallet_id,
            "counterparty_wallet_id": counterparty_wallet_id,
            "amount_asset": amount_asset,
            "amount_twd_equiv": None if amount_asset is None or rate_twd is None else amount_asset * rate_twd,
            "tx_hash": None,
            "status": "completed",
        })
        if row.get("source_ip_hash"):
            crypto_events_for_login.append({
                "event_id": f"crypto_{row['id']}",
                "user_id": user_id,
                "occurred_at": occurred_at,
                "ip_address": str(row["source_ip_hash"]),
                "app_channel": None,
            })

    activity_window_by_user: dict[str, str] = {}
    for uid, times in observed_activity.items():
        if not times:
            continue
        earliest = min(times).date().isoformat()
        latest = max(times).date().isoformat()
        activity_window_by_user[uid] = f"{earliest}..{latest}"

    users_by_id: dict[str, dict[str, Any]] = {}
    for row in user_info:
        uid = str(row["user_id"])
        created_at = derive_user_created_at(row)
        users_by_id[uid] = {
            "user_id": uid,
            "created_at": format_source_datetime(created_at),
            "segment": USER_SOURCE_LABELS.get(coerce_int(row.get("user_source"), -1)),
            "kyc_level": derive_kyc_level(row),
            "occupation": None if row.get("career") in (None, "") else f"career_{row['career']}",
            "monthly_income_twd": None,
            "expected_monthly_volume_twd": None,
            "declared_source_of_funds": None if row.get("income_source") in (None, "") else f"income_source_{row['income_source']}",
            "residence_country": None,
            "residence_city": None,
            "nationality": None,
            "activity_window": activity_window_by_user.get(uid),
        }

    for uid, times in observed_activity.items():
        if uid in users_by_id:
            if users_by_id[uid]["activity_window"] is None:
                users_by_id[uid]["activity_window"] = activity_window_by_user.get(uid)
            if users_by_id[uid]["created_at"] is None and times:
                users_by_id[uid]["created_at"] = format_source_datetime(min(times))
            continue
        users_by_id[uid] = {
            "user_id": uid,
            "created_at": format_source_datetime(min(times)) if times else None,
            "segment": None,
            "kyc_level": None,
            "occupation": None,
            "monthly_income_twd": None,
            "expected_monthly_volume_twd": None,
            "declared_source_of_funds": None,
            "residence_country": None,
            "residence_city": None,
            "nationality": None,
            "activity_window": activity_window_by_user.get(uid),
        }

    login_events, devices, user_device_links = build_synthetic_login_views(
        fiat_events_for_login + trade_events_for_login + crypto_events_for_login
    )

    earliest_activity_by_user = {
        uid: min(times)
        for uid, times in observed_activity.items()
        if times
    }
    known_blacklist_users: list[dict[str, Any]] = []
    for row in train_label:
        if coerce_int(row.get("status"), 0) != 1:
            continue
        uid = str(row["user_id"])
        observed_at = earliest_activity_by_user.get(uid)
        if observed_at is None:
            user_created_at = users_by_id.get(uid, {}).get("created_at")
            observed_at = parse_upstream_datetime(user_created_at)
        known_blacklist_users.append({
            "blacklist_entry_id": f"kbl_{uid}",
            "user_id": uid,
            "observed_at": format_source_datetime(observed_at),
            "source": "bitopro_train_label",
            "reason_code": "train_label_status_1",
            "is_active": True,
        })

    return {
        "users": _sort_rows(list(users_by_id.values()), "created_at", "user_id"),
        "login_events": _sort_rows(login_events, "occurred_at", "login_id"),
        "fiat_transactions": _sort_rows(fiat_transactions, "occurred_at", "fiat_txn_id"),
        "trade_orders": _sort_rows(trade_orders, "occurred_at", "trade_id"),
        "crypto_transactions": _sort_rows(crypto_transactions, "occurred_at", "crypto_txn_id"),
        "known_blacklist_users": _sort_rows(known_blacklist_users, "observed_at", "blacklist_entry_id"),
        "devices": _sort_rows(devices, "first_seen_at", "device_id"),
        "user_device_links": _sort_rows(user_device_links, "first_seen_at", "link_id"),
        "bank_accounts": [],
        "user_bank_links": [],
        "crypto_wallets": _sort_rows(list(wallet_records.values()), "created_at", "wallet_id"),
    }


def build_synthetic_login_views(
    activity_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build login_events from IP activity rows without fabricating device identity."""
    ordered = sorted(
        activity_rows,
        key=lambda item: (item["user_id"], item["occurred_at"], item["event_id"]),
    )
    login_events: list[dict[str, Any]] = []

    for item in ordered:
        ip_address = item.get("ip_address")
        if not ip_address:
            continue
        occurred_at = item["occurred_at"]
        login_events.append({
            "login_id": f"login_{item['event_id']}",
            "user_id": item["user_id"],
            "occurred_at": format_source_datetime(occurred_at),
            "device_id": None,
            "ip_address": ip_address,
            "ip_country": None,
            "ip_city": None,
            "is_vpn": False,
            "is_new_device": False,
            "is_geo_jump": False,
            "success": True,
        })

    return login_events, [], []
