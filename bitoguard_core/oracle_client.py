from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from source_client import detect_postgrest_openapi


@dataclass(frozen=True)
class OraclePayload:
    user_labels: pd.DataFrame
    scenarios: pd.DataFrame


def empty_scenarios_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "scenario_id",
            "scenario_type",
            "start_at",
            "end_at",
            "description",
        ]
    )


class OracleClient:
    def __init__(
        self,
        oracle_dir: Path | None = None,
        *,
        source_url: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.oracle_dir = oracle_dir
        self.source_url = source_url.rstrip("/") if source_url else None
        self.timeout = timeout
        self.transport = transport

    def load(self) -> OraclePayload:
        if self.source_url and self._is_postgrest_source():
            return self._load_postgrest_labels()
        if self.oracle_dir is None:
            raise ValueError("oracle_dir is required when no remote source_url is configured")
        return self._load_local_files()

    def _is_postgrest_source(self) -> bool:
        if not self.source_url:
            return False
        with httpx.Client(base_url=self.source_url, timeout=self.timeout, transport=self.transport) as client:
            try:
                response = client.get("/", headers={"Accept": "application/json"})
                response.raise_for_status()
                return detect_postgrest_openapi(response.json())
            except Exception:
                return False

    def _load_local_files(self) -> OraclePayload:
        if self.oracle_dir is None:
            raise ValueError("oracle_dir is not configured")
        users = pd.read_csv(self.oracle_dir / "users.csv")
        scenarios = pd.read_csv(self.oracle_dir / "scenarios.csv")
        user_labels = users[
            [
                "user_id",
                "hidden_suspicious_label",
                "observed_blacklist_label",
                "scenario_types",
                "evidence_tags",
            ]
        ].copy()
        return OraclePayload(user_labels=user_labels, scenarios=scenarios)

    def _load_postgrest_labels(self) -> OraclePayload:
        if self.source_url is None:
            raise ValueError("source_url is not configured")
        with httpx.Client(base_url=self.source_url, timeout=self.timeout, transport=self.transport) as client:
            rows = self._fetch_all_rows(client, "/train_label", "user_id")

        user_labels = pd.DataFrame(
            [
                {
                    "user_id": str(row["user_id"]),
                    "hidden_suspicious_label": int(row.get("status", 0) or 0),
                    "observed_blacklist_label": int(row.get("status", 0) or 0),
                    "scenario_types": "",
                    "evidence_tags": "",
                }
                for row in rows
            ]
        )
        if user_labels.empty:
            user_labels = pd.DataFrame(
                columns=[
                    "user_id",
                    "hidden_suspicious_label",
                    "observed_blacklist_label",
                    "scenario_types",
                    "evidence_tags",
                ]
            )
        return OraclePayload(user_labels=user_labels, scenarios=empty_scenarios_frame())

    def _fetch_all_rows(self, client: httpx.Client, path: str, sort_field: str, page_size: int = 1000) -> list[dict[str, Any]]:
        offset = 0
        rows: list[dict[str, Any]] = []
        while True:
            response = client.get(
                path,
                params={
                    "order": f"{sort_field}.asc",
                    "limit": page_size,
                    "offset": offset,
                },
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)
        return rows
