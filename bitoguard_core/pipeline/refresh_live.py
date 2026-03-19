from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

import duckdb
import pandas as pd

from config import load_settings
from db.store import DuckDBStore, utc_now
from features.build_features import build_feature_snapshots
from features.graph_features import build_graph_features
from models.score import score_latest_snapshot
from pipeline.rebuild_edges import rebuild_edges
from services.drift import run_score_drift_check
from services.model_monitor import check_model_staleness, check_score_sanity

_SAFE_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_column_name(col: str) -> str:
    if not _SAFE_COLUMN_RE.match(col):
        raise ValueError(f"Column name {col!r} contains invalid characters")
    return col


PIPELINE_NAME = "refresh_live"
REFRESH_MODE = "latest_snapshot_incremental"
FIRST_RUN_LOOKBACK = pd.Timedelta(days=30)
SAFETY_OVERLAP = pd.Timedelta(days=1)
TARGET_FEATURE_TABLES = (
    "features.graph_features",
    "features.feature_snapshots_user_day",
    "features.feature_snapshots_user_30d",
)


def _coerce_timestamp(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _timestamp_json(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _json_default(value: object) -> str:
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return str(value)


def _stage_marker(stage: str, started_at: float, **metrics: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in metrics.items() if value is not None)
    suffix = f" {details}" if details else ""
    logger.info("stage=%s elapsed_s=%.2f%s", stage, time.perf_counter() - started_at, suffix)


def _read_refresh_state(store: DuckDBStore) -> dict[str, Any] | None:
    state = store.fetch_df(
        "SELECT * FROM ops.refresh_state WHERE pipeline_name = ?",
        (PIPELINE_NAME,),
    )
    if state.empty:
        return None
    return state.iloc[0].to_dict()


def _write_refresh_state(
    store: DuckDBStore,
    *,
    status: str,
    last_success_at: pd.Timestamp | None,
    last_source_event_at: pd.Timestamp | None,
    last_run_started_at: pd.Timestamp,
    last_run_finished_at: pd.Timestamp | None,
    last_error: str | None,
    details: dict[str, Any],
) -> None:
    details_json = json.dumps(details, ensure_ascii=False, default=_json_default)
    with store.transaction() as conn:
        conn.execute("DELETE FROM ops.refresh_state WHERE pipeline_name = ?", (PIPELINE_NAME,))
        conn.execute(
            """
            INSERT INTO ops.refresh_state (
                pipeline_name,
                status,
                last_success_at,
                last_source_event_at,
                last_run_started_at,
                last_run_finished_at,
                last_error,
                details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PIPELINE_NAME,
                status,
                last_success_at,
                last_source_event_at,
                last_run_started_at,
                last_run_finished_at,
                last_error,
                details_json,
            ),
        )


def _current_source_event_at(store: DuckDBStore) -> pd.Timestamp | None:
    current = store.fetch_df(
        """
        SELECT MAX(event_at) AS current_source_event_at
        FROM (
            SELECT MAX(TRY_CAST(occurred_at AS TIMESTAMPTZ)) AS event_at FROM canonical.login_events
            UNION ALL
            SELECT MAX(TRY_CAST(occurred_at AS TIMESTAMPTZ)) AS event_at FROM canonical.fiat_transactions
            UNION ALL
            SELECT MAX(TRY_CAST(occurred_at AS TIMESTAMPTZ)) AS event_at FROM canonical.trade_orders
            UNION ALL
            SELECT MAX(TRY_CAST(occurred_at AS TIMESTAMPTZ)) AS event_at FROM canonical.crypto_transactions
            UNION ALL
            SELECT MAX(TRY_CAST(observed_at AS TIMESTAMPTZ)) AS event_at FROM canonical.blacklist_feed
            UNION ALL
            SELECT MAX(TRY_CAST(first_seen_at AS TIMESTAMPTZ)) AS event_at FROM canonical.user_device_links
            UNION ALL
            SELECT MAX(TRY_CAST(last_seen_at AS TIMESTAMPTZ)) AS event_at FROM canonical.user_device_links
            UNION ALL
            SELECT MAX(TRY_CAST(linked_at AS TIMESTAMPTZ)) AS event_at FROM canonical.user_bank_links
            UNION ALL
            SELECT MAX(TRY_CAST(created_at AS TIMESTAMPTZ)) AS event_at FROM canonical.crypto_wallets
        )
        """
    )
    return _coerce_timestamp(current.iloc[0]["current_source_event_at"])


def _derive_direct_user_ids(
    store: DuckDBStore,
    window_start: pd.Timestamp,
    current_source_event_at: pd.Timestamp,
) -> list[str]:
    affected = store.fetch_df(
        """
        WITH direct_users AS (
            SELECT DISTINCT user_id
            FROM canonical.login_events
            WHERE user_id IS NOT NULL AND occurred_at >= ? AND occurred_at <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.fiat_transactions
            WHERE user_id IS NOT NULL AND occurred_at >= ? AND occurred_at <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.trade_orders
            WHERE user_id IS NOT NULL AND occurred_at >= ? AND occurred_at <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.crypto_transactions
            WHERE user_id IS NOT NULL AND occurred_at >= ? AND occurred_at <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.blacklist_feed
            WHERE user_id IS NOT NULL AND observed_at >= ? AND observed_at <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.user_bank_links
            WHERE user_id IS NOT NULL
                AND TRY_CAST(linked_at AS TIMESTAMPTZ) >= ?
                AND TRY_CAST(linked_at AS TIMESTAMPTZ) <= ?
            UNION
            SELECT DISTINCT user_id
            FROM canonical.user_device_links
            WHERE user_id IS NOT NULL AND (
                (TRY_CAST(first_seen_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(first_seen_at AS TIMESTAMPTZ) <= ?)
                OR (TRY_CAST(last_seen_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(last_seen_at AS TIMESTAMPTZ) <= ?)
            )
            UNION
            SELECT DISTINCT user_id
            FROM canonical.crypto_wallets
            WHERE user_id IS NOT NULL
                AND TRY_CAST(created_at AS TIMESTAMPTZ) >= ?
                AND TRY_CAST(created_at AS TIMESTAMPTZ) <= ?
        )
        SELECT DISTINCT user_id
        FROM direct_users
        WHERE user_id IS NOT NULL
        ORDER BY user_id
        """,
        (
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
        ),
    )
    return affected["user_id"].astype(str).tolist() if not affected.empty else []


def _derive_affected_user_ids(
    store: DuckDBStore,
    window_start: pd.Timestamp,
    current_source_event_at: pd.Timestamp,
) -> list[str]:
    return _derive_direct_user_ids(store, window_start, current_source_event_at)


def _expand_graph_affected_user_ids(store: DuckDBStore, direct_user_ids: list[str]) -> list[str]:
    if not direct_user_ids:
        return []

    placeholders = ", ".join(["?"] * len(direct_user_ids))
    related = store.fetch_df(
        f"""
        SELECT DISTINCT related.src_id AS user_id
        FROM canonical.entity_edges AS changed
        INNER JOIN canonical.entity_edges AS related
            ON related.dst_type = changed.dst_type
            AND related.dst_id = changed.dst_id
        WHERE changed.src_type = 'user'
            AND related.src_type = 'user'
            AND changed.src_id IN ({placeholders})
        ORDER BY user_id
        """,
        tuple(direct_user_ids),
    )
    if related.empty:
        return sorted(set(direct_user_ids))
    return sorted(set(direct_user_ids) | set(related["user_id"].astype(str).tolist()))


def _graph_rebuild_required(
    store: DuckDBStore,
    window_start: pd.Timestamp,
    current_source_event_at: pd.Timestamp,
) -> bool:
    changed_graph_links = store.fetch_df(
        """
        SELECT COUNT(*) AS n
        FROM (
            SELECT link_id
            FROM canonical.user_bank_links
            WHERE TRY_CAST(linked_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(linked_at AS TIMESTAMPTZ) <= ?
            UNION ALL
            SELECT link_id
            FROM canonical.user_device_links
            WHERE (
                TRY_CAST(first_seen_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(first_seen_at AS TIMESTAMPTZ) <= ?
            ) OR (
                TRY_CAST(last_seen_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(last_seen_at AS TIMESTAMPTZ) <= ?
            )
            UNION ALL
            SELECT wallet_id
            FROM canonical.crypto_wallets
            WHERE TRY_CAST(created_at AS TIMESTAMPTZ) >= ? AND TRY_CAST(created_at AS TIMESTAMPTZ) <= ?
        )
        """,
        (
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
            window_start,
            current_source_event_at,
        ),
    )
    if int(changed_graph_links.iloc[0]["n"]) > 0:
        return True

    edge_count = store.fetch_df("SELECT COUNT(*) AS n FROM canonical.entity_edges")
    return int(edge_count.iloc[0]["n"]) == 0


def _duckdb_type_for_series(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMPTZ"
    return "VARCHAR"


def _ensure_table_columns(conn: duckdb.DuckDBPyConnection, table_name: str, dataframe: pd.DataFrame) -> list[str]:
    existing_columns = conn.execute(f"SELECT * FROM {table_name} LIMIT 0").df().columns.tolist()
    for column in dataframe.columns:
        if column in existing_columns:
            continue
        safe_col = _safe_column_name(column)
        conn.execute(
            f'ALTER TABLE {table_name} ADD COLUMN "{safe_col}" {_duckdb_type_for_series(dataframe[column])}'
        )
        existing_columns.append(column)
    return conn.execute(f"SELECT * FROM {table_name} LIMIT 0").df().columns.tolist()


def _upsert_snapshot_rows(
    store: DuckDBStore,
    table_name: str,
    snapshot_date: pd.Timestamp,
    target_user_ids: list[str],
    dataframe: pd.DataFrame,
) -> dict[str, int]:
    if not target_user_ids:
        return {"deleted_rows": 0, "inserted_rows": 0}

    snapshot_value = pd.Timestamp(snapshot_date).date()
    target_user_frame = pd.DataFrame({"user_id": target_user_ids})
    inserted_rows = int(len(dataframe))

    with store.transaction() as conn:
        existing_columns = _ensure_table_columns(conn, table_name, dataframe)
        conn.register("target_user_ids", target_user_frame)
        deleted_rows = int(conn.execute(
            f"""
            SELECT COUNT(*) AS row_count
            FROM {table_name}
            WHERE snapshot_date = ?
                AND user_id IN (SELECT user_id FROM target_user_ids)
            """,
            (snapshot_value,),
        ).fetchone()[0])
        conn.execute(
            f"""
            DELETE FROM {table_name}
            WHERE snapshot_date = ?
                AND user_id IN (SELECT user_id FROM target_user_ids)
            """,
            (snapshot_value,),
        )
        if inserted_rows > 0:
            aligned = dataframe.copy()
            for column in existing_columns:
                if column not in aligned.columns:
                    aligned[column] = pd.NA
            aligned = aligned[existing_columns]
            conn.register("target_rows", aligned)
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM target_rows")
            conn.unregister("target_rows")
        conn.unregister("target_user_ids")

    return {
        "deleted_rows": deleted_rows,
        "inserted_rows": inserted_rows,
    }


def _base_summary(
    *,
    status: str,
    no_op: bool,
    current_source_event_at: pd.Timestamp | None,
    window_start: pd.Timestamp | None,
) -> dict[str, Any]:
    return {
        "mode": REFRESH_MODE,
        "status": status,
        "no_op": no_op,
        "current_source_event_at": _timestamp_json(current_source_event_at),
        "window_start": _timestamp_json(window_start),
        "affected_user_count": 0,
        "updated_row_counts": {
            "features.graph_features": 0,
            "features.feature_snapshots_user_day": 0,
            "features.feature_snapshots_user_30d": 0,
        },
    }


def refresh_live() -> dict[str, Any]:
    settings = load_settings()
    store = DuckDBStore(settings.db_path)
    started_at = time.perf_counter()
    run_started_at = _coerce_timestamp(utc_now())
    state = _read_refresh_state(store)
    prior_last_success_at = _coerce_timestamp(state.get("last_success_at")) if state else None
    prior_watermark = _coerce_timestamp(state.get("last_source_event_at")) if state else None
    current_source_event_at: pd.Timestamp | None = None
    window_start: pd.Timestamp | None = None
    affected_user_ids: list[str] = []
    updated_row_counts = {
        "features.graph_features": 0,
        "features.feature_snapshots_user_day": 0,
        "features.feature_snapshots_user_30d": 0,
    }

    _write_refresh_state(
        store,
        status="running",
        last_success_at=prior_last_success_at,
        last_source_event_at=prior_watermark,
        last_run_started_at=run_started_at,
        last_run_finished_at=None,
        last_error=None,
        details={"mode": REFRESH_MODE, "status": "running"},
    )
    _stage_marker("start", started_at, mode=REFRESH_MODE, last_source_event_at=_timestamp_json(prior_watermark))

    # Model staleness check: warn if model bundle is ageing, error if critically stale
    try:
        _bundle_path = settings.artifact_dir / "official_bundle.json"
        if _bundle_path.exists():
            _staleness = check_model_staleness(_bundle_path)
            _stage_marker(
                "model_staleness_check",
                started_at,
                staleness=_staleness.staleness_level,
                age_days=_staleness.age_days,
            )
    except Exception as _stale_exc:
        logger.warning("Model staleness check failed (non-fatal): %s", _stale_exc)

    try:
        current_source_event_at = _current_source_event_at(store)
        if current_source_event_at is None:
            summary = _base_summary(
                status="success",
                no_op=True,
                current_source_event_at=None,
                window_start=None,
            )
            finished_at = _coerce_timestamp(utc_now())
            _write_refresh_state(
                store,
                status="success",
                last_success_at=finished_at,
                last_source_event_at=prior_watermark,
                last_run_started_at=run_started_at,
                last_run_finished_at=finished_at,
                last_error=None,
                details=summary,
            )
            _stage_marker("no_source_data", started_at, no_op=True)
            return summary

        window_start = (
            current_source_event_at - FIRST_RUN_LOOKBACK
            if prior_watermark is None
            else prior_watermark - SAFETY_OVERLAP
        )
        _stage_marker(
            "watermark",
            started_at,
            current_source_event_at=_timestamp_json(current_source_event_at),
            window_start=_timestamp_json(window_start),
        )

        if prior_watermark is not None and current_source_event_at <= prior_watermark:
            summary = _base_summary(
                status="success",
                no_op=True,
                current_source_event_at=current_source_event_at,
                window_start=window_start,
            )
            finished_at = _coerce_timestamp(utc_now())
            _write_refresh_state(
                store,
                status="success",
                last_success_at=finished_at,
                last_source_event_at=prior_watermark,
                last_run_started_at=run_started_at,
                last_run_finished_at=finished_at,
                last_error=None,
                details=summary,
            )
            _stage_marker("no_op", started_at, no_op=True, reason="watermark_current")
            return summary

        direct_user_ids = _derive_direct_user_ids(store, window_start, current_source_event_at)
        affected_user_ids = direct_user_ids
        latest_snapshot_date = current_source_event_at.tz_localize(None).normalize()
        _stage_marker("affected_users", started_at, affected_user_count=len(direct_user_ids))

        predictions: pd.DataFrame | None = None
        _score_psi_info: dict[str, object] = {}
        if direct_user_ids:
            if _graph_rebuild_required(store, window_start, current_source_event_at):
                rebuild_edges()
            affected_user_ids = _expand_graph_affected_user_ids(store, direct_user_ids)
            _stage_marker(
                "affected_users_expanded",
                started_at,
                direct_user_count=len(direct_user_ids),
                affected_user_count=len(affected_user_ids),
            )
            graph_df = build_graph_features(
                snapshot_dates=[latest_snapshot_date],
                target_user_ids=affected_user_ids,
                persist=False,
            )
            _stage_marker(
                "graph_features_built",
                started_at,
                affected_user_count=len(affected_user_ids),
                row_count=len(graph_df),
            )
            graph_update = _upsert_snapshot_rows(
                store,
                "features.graph_features",
                latest_snapshot_date,
                affected_user_ids,
                graph_df,
            )
            updated_row_counts["features.graph_features"] = graph_update["inserted_rows"]
            _stage_marker(
                "graph_features_upserted",
                started_at,
                deleted_rows=graph_update["deleted_rows"],
                row_count=graph_update["inserted_rows"],
            )

            user_day_df, user_30d_df = build_feature_snapshots(
                snapshot_dates=[latest_snapshot_date],
                target_user_ids=affected_user_ids,
                persist=False,
            )
            _stage_marker(
                "feature_snapshots_built",
                started_at,
                affected_user_count=len(affected_user_ids),
                user_day_rows=len(user_day_df),
                user_30d_rows=len(user_30d_df),
            )

            user_day_update = _upsert_snapshot_rows(
                store,
                "features.feature_snapshots_user_day",
                latest_snapshot_date,
                affected_user_ids,
                user_day_df,
            )
            user_30d_update = _upsert_snapshot_rows(
                store,
                "features.feature_snapshots_user_30d",
                latest_snapshot_date,
                affected_user_ids,
                user_30d_df,
            )
            updated_row_counts["features.feature_snapshots_user_day"] = user_day_update["inserted_rows"]
            updated_row_counts["features.feature_snapshots_user_30d"] = user_30d_update["inserted_rows"]
            _stage_marker(
                "feature_snapshots_upserted",
                started_at,
                user_day_deleted=user_day_update["deleted_rows"],
                user_day_rows=user_day_update["inserted_rows"],
                user_30d_deleted=user_30d_update["deleted_rows"],
                user_30d_rows=user_30d_update["inserted_rows"],
            )

            if not user_day_df.empty:
                predictions = score_latest_snapshot()
                _stage_marker(
                    "score_latest_snapshot",
                    started_at,
                    prediction_rows=len(predictions),
                    high_risk_count=int(predictions["risk_level"].isin(["high", "critical"]).sum()),
                )
                # Score sanity: verify score distribution is in expected ranges
                try:
                    import numpy as _np
                    _scores_arr = _np.asarray(predictions["model_score"].dropna(), dtype=float)
                    _sanity = check_score_sanity(_scores_arr)
                    _score_psi_info["score_sanity_ok"] = _sanity.health_ok
                    if not _sanity.health_ok:
                        logger.warning("Score sanity failed: %s", _sanity.checks_failed)
                except Exception as _san_exc:
                    logger.warning("Score sanity check failed (non-fatal): %s", _san_exc)
                # PSI-based score distribution monitoring: detect silent model degradation
                # between consecutive scoring runs. Logs warning at PSI ≥ 0.10 (moderate)
                # or ≥ 0.25 (severe). Result captured in summary for ops observability.
                try:
                    _score_drift = run_score_drift_check(str(settings.db_path))
                    if _score_drift is not None:
                        _score_psi_info["score_psi"] = _score_drift.psi
                        _score_psi_info["score_psi_severity"] = _score_drift.psi_severity
                        _stage_marker(
                            "score_distribution_check",
                            started_at,
                            psi=round(_score_drift.psi, 4),
                            severity=_score_drift.psi_severity,
                        )
                except Exception as _drift_exc:
                    logger.warning("Score drift check failed (non-fatal): %s", _drift_exc)

        no_op = sum(updated_row_counts.values()) == 0 and predictions is None
        summary = _base_summary(
            status="success",
            no_op=no_op,
            current_source_event_at=current_source_event_at,
            window_start=window_start,
        )
        summary["affected_user_count"] = len(affected_user_ids)
        summary["updated_row_counts"] = updated_row_counts
        if predictions is not None:
            summary["prediction_rows"] = int(len(predictions))
            summary["high_risk_count"] = int(predictions["risk_level"].isin(["high", "critical"]).sum())
        summary.update(_score_psi_info)  # score_psi, score_psi_severity, score_sanity_ok

        finished_at = _coerce_timestamp(utc_now())
        _write_refresh_state(
            store,
            status="success",
            last_success_at=finished_at,
            last_source_event_at=current_source_event_at,
            last_run_started_at=run_started_at,
            last_run_finished_at=finished_at,
            last_error=None,
            details=summary,
        )
        _stage_marker(
            "complete",
            started_at,
            status="success",
            no_op=no_op,
            affected_user_count=len(affected_user_ids),
        )
        return summary
    except Exception as exc:
        finished_at = _coerce_timestamp(utc_now())
        failure_summary = _base_summary(
            status="failed",
            no_op=False,
            current_source_event_at=current_source_event_at,
            window_start=window_start,
        )
        failure_summary["affected_user_count"] = len(affected_user_ids)
        failure_summary["updated_row_counts"] = updated_row_counts
        failure_summary["last_error"] = str(exc)
        _write_refresh_state(
            store,
            status="failed",
            last_success_at=prior_last_success_at,
            last_source_event_at=prior_watermark,
            last_run_started_at=run_started_at,
            last_run_finished_at=finished_at,
            last_error=str(exc),
            details=failure_summary,
        )
        _stage_marker("failed", started_at, error=str(exc))
        raise


def refresh_live_with_retry(
    max_retries: int = 2,
    retry_delay_s: float = 5.0,
) -> dict[str, Any]:
    """Run refresh_live() with exponential-backoff retry for transient failures.

    Retries on:
    - duckdb.IOException (lock contention — another writer holds the DB)
    - ConnectionError / TimeoutError (transient network failures to source API)

    Does NOT retry on: ValueError, KeyError, RuntimeError, or other logic errors,
    as those indicate non-transient failures that require investigation.

    Args:
        max_retries: Maximum number of retry attempts after the initial failure.
        retry_delay_s: Initial delay in seconds before the first retry.
                       Doubles on each subsequent retry (exponential backoff).

    Returns:
        Summary dict from refresh_live() on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    import duckdb
    _RETRYABLE = (duckdb.IOException, ConnectionError, TimeoutError)
    attempt = 0
    last_exc: BaseException | None = None
    delay = retry_delay_s
    while attempt <= max_retries:
        try:
            return refresh_live()
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            logger.warning(
                "Transient refresh failure (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, max_retries + 1, exc, delay,
            )
            time.sleep(delay)
            delay *= 2.0
            attempt += 1
    assert last_exc is not None
    raise last_exc


def main() -> dict[str, Any]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    summary = refresh_live_with_retry()
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
