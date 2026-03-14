from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd

from config import load_settings
from db.store import DuckDBStore, make_id, utc_now
from source_client import SOURCE_ENDPOINTS, SourceClient


def _reconcile_abandoned_sync_runs(store: DuckDBStore, sync_run_id: str, reconciled_at: datetime) -> None:
    store.execute(
        """
        UPDATE ops.sync_runs
        SET finished_at = ?,
            status = ?,
            error_message = CASE
                WHEN error_message IS NULL OR error_message = '' THEN ?
                ELSE error_message
            END
        WHERE status = 'running' AND finished_at IS NULL
        """,
        (
            reconciled_at,
            "failed",
            f"abandoned by newer sync run {sync_run_id}",
        ),
    )


def _persist_row_summary(store: DuckDBStore, sync_run_id: str, summary: dict[str, int]) -> None:
    store.execute(
        """
        UPDATE ops.sync_runs
        SET row_summary = ?
        WHERE sync_run_id = ?
        """,
        (json.dumps(summary), sync_run_id),
    )


def sync_source(start_time: datetime | None = None, end_time: datetime | None = None) -> str:
    settings = load_settings()
    store = DuckDBStore(settings.db_path)
    client = SourceClient(settings.source_url)
    sync_run_id = make_id("sync")
    started_at = utc_now()
    is_full_sync = start_time is None and end_time is None
    progress_summary: dict[str, int] = {}
    _reconcile_abandoned_sync_runs(store, sync_run_id, started_at)
    store.execute(
        """
        INSERT INTO ops.sync_runs (
            sync_run_id, started_at, finished_at, source_url, sync_mode, start_time, end_time, status, row_summary, error_message
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            sync_run_id,
            started_at,
            settings.source_url,
            "incremental" if (start_time or end_time) else "full",
            start_time,
            end_time,
            "running",
            json.dumps({}),
        ),
    )

    try:
        def persist_fetch_progress(table_name: str, row_count: int) -> None:
            progress_summary[table_name] = row_count
            _persist_row_summary(store, sync_run_id, progress_summary)

        payload = client.fetch_all(
            start_time=start_time,
            end_time=end_time,
            progress_callback=persist_fetch_progress,
        )
        summary: dict[str, int] = {}
        loaded_at = utc_now()
        with store.transaction() as conn:
            if is_full_sync:
                for endpoint in SOURCE_ENDPOINTS:
                    conn.execute(f"DELETE FROM raw.{endpoint.name}")
            for endpoint in SOURCE_ENDPOINTS:
                dataframe = pd.DataFrame(payload[endpoint.name])
                summary[endpoint.name] = len(dataframe)
                if dataframe.empty:
                    continue
                dataframe["_sync_run_id"] = sync_run_id
                dataframe["_loaded_at"] = loaded_at
                conn.register("raw_df", dataframe)
                conn.execute(f"INSERT INTO raw.{endpoint.name} SELECT * FROM raw_df")
                conn.unregister("raw_df")
        store.execute(
            """
            UPDATE ops.sync_runs
            SET finished_at = ?, status = ?, row_summary = ?
            WHERE sync_run_id = ?
            """,
            (utc_now(), "completed", json.dumps(summary), sync_run_id),
        )
        return sync_run_id
    except Exception as exc:  # pragma: no cover - operational path
        store.execute(
            """
            UPDATE ops.sync_runs
            SET finished_at = ?, status = ?, error_message = ?
            WHERE sync_run_id = ?
            """,
            (utc_now(), "failed", str(exc), sync_run_id),
        )
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync source API into raw DuckDB tables.")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sync_source(
        start_time=datetime.fromisoformat(args.start_time) if args.start_time else None,
        end_time=datetime.fromisoformat(args.end_time) if args.end_time else None,
    )
