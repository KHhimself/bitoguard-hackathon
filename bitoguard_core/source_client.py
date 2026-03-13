"""BitoPro source API HTTP client.

Handles HTTP pagination and protocol detection only.
All schema transformation logic lives in pipeline/transformers.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from pipeline.transformers import project_postgrest_payload


@dataclass(frozen=True)
class SourceEndpoint:
    name: str
    path: str
    primary_key: str


@dataclass(frozen=True)
class PostgrestTable:
    path: str
    time_field: str | None
    sort_field: str


SOURCE_ENDPOINTS: tuple[SourceEndpoint, ...] = (
    SourceEndpoint("users", "/v1/users", "user_id"),
    SourceEndpoint("login_events", "/v1/login-events", "login_id"),
    SourceEndpoint("fiat_transactions", "/v1/fiat-transactions", "fiat_txn_id"),
    SourceEndpoint("trade_orders", "/v1/trade-orders", "trade_id"),
    SourceEndpoint("crypto_transactions", "/v1/crypto-transactions", "crypto_txn_id"),
    SourceEndpoint("known_blacklist_users", "/v1/known-blacklist-users", "blacklist_entry_id"),
    SourceEndpoint("devices", "/v1/devices", "device_id"),
    SourceEndpoint("user_device_links", "/v1/user-device-links", "link_id"),
    SourceEndpoint("bank_accounts", "/v1/bank-accounts", "bank_account_id"),
    SourceEndpoint("user_bank_links", "/v1/user-bank-links", "link_id"),
    SourceEndpoint("crypto_wallets", "/v1/crypto-wallets", "wallet_id"),
)

POSTGREST_TABLES: dict[str, PostgrestTable] = {
    "user_info": PostgrestTable("/user_info", "confirmed_at", "user_id"),
    "twd_transfer": PostgrestTable("/twd_transfer", "created_at", "id"),
    "usdt_twd_trading": PostgrestTable("/usdt_twd_trading", "updated_at", "id"),
    "usdt_swap": PostgrestTable("/usdt_swap", "created_at", "id"),
    "crypto_transfer": PostgrestTable("/crypto_transfer", "created_at", "id"),
    "train_label": PostgrestTable("/train_label", None, "user_id"),
}


def detect_postgrest_openapi(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    paths = payload.get("paths")
    return isinstance(paths, dict) and "/user_info" in paths and "/crypto_transfer" in paths


class SourceClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def fetch_all(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page_size: int = 1000,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
            if self._is_postgrest_source(client):
                return self._fetch_postgrest_all(client, start_time, end_time, page_size, progress_callback)
            return {
                endpoint.name: self._fetch_v1_endpoint(client, endpoint.path, start_time, end_time, page_size)
                for endpoint in SOURCE_ENDPOINTS
            }

    def _is_postgrest_source(self, client: httpx.Client) -> bool:
        try:
            response = client.get("/", headers={"Accept": "application/json"})
            response.raise_for_status()
            return detect_postgrest_openapi(response.json())
        except Exception:
            return False

    def _fetch_v1_endpoint(
        self,
        client: httpx.Client,
        path: str,
        start_time: datetime | None,
        end_time: datetime | None,
        page_size: int,
    ) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"page": page, "page_size": page_size}
            if start_time is not None:
                params["start_time"] = start_time.isoformat()
            if end_time is not None:
                params["end_time"] = end_time.isoformat()
            response = client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
            items.extend(payload["items"])
            if not payload["has_next"]:
                break
            page += 1
        return items

    def _fetch_postgrest_all(
        self,
        client: httpx.Client,
        start_time: datetime | None,
        end_time: datetime | None,
        page_size: int,
        progress_callback: Callable[[str, int], None] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        upstream_payload: dict[str, list[dict[str, Any]]] = {}
        for name, table in POSTGREST_TABLES.items():
            table_progress_callback = None
            if progress_callback is not None:
                def table_progress_callback(row_count: int, table_name: str = name) -> None:
                    progress_callback(table_name, row_count)

            upstream_payload[name] = self._fetch_postgrest_table(
                client,
                table,
                start_time=start_time if name != "train_label" else None,
                end_time=end_time if name != "train_label" else None,
                page_size=page_size,
                progress_callback=table_progress_callback,
            )
            if progress_callback is not None:
                progress_callback(name, len(upstream_payload[name]))
        return project_postgrest_payload(upstream_payload)

    def _fetch_postgrest_table(
        self,
        client: httpx.Client,
        table: PostgrestTable,
        *,
        start_time: datetime | None,
        end_time: datetime | None,
        page_size: int,
        progress_callback: Callable[[int], None] | None = None,
    ) -> list[dict[str, Any]]:
        offset = 0
        rows: list[dict[str, Any]] = []
        while True:
            params: list[tuple[str, str | int]] = [
                ("order", f"{table.sort_field}.asc"),
                ("limit", page_size),
                ("offset", offset),
            ]
            if table.time_field and start_time and end_time:
                params.append((
                    "and",
                    f"({table.time_field}.gte.{self._format_postgrest_time(start_time)},{table.time_field}.lt.{self._format_postgrest_time(end_time)})",
                ))
            elif table.time_field and start_time:
                params.append((table.time_field, f"gte.{self._format_postgrest_time(start_time)}"))
            elif table.time_field and end_time:
                params.append((table.time_field, f"lt.{self._format_postgrest_time(end_time)}"))

            response = client.get(table.path, params=params)
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            if progress_callback is not None:
                progress_callback(len(rows))
            if len(batch) < page_size:
                break
            offset += len(batch)
        return rows

    def _format_postgrest_time(self, value: datetime) -> str:
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.replace(tzinfo=None).isoformat(timespec="seconds")
