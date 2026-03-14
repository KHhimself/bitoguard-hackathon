from __future__ import annotations
from pathlib import Path
import pandas as pd
import pytest
from db.store import DuckDBStore


def test_replace_table_rejects_unknown_table(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "t.duckdb")
    with pytest.raises(ValueError, match="not in the allowed"):
        store.replace_table("evil.inject", pd.DataFrame({"x": [1]}))


def test_read_table_rejects_unknown_table(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "t.duckdb")
    with pytest.raises(ValueError, match="not in the allowed"):
        store.read_table("ops.nonexistent_table")


def test_append_rejects_unknown_table(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "t.duckdb")
    with pytest.raises(ValueError, match="not in the allowed"):
        store.append_dataframe("'; DROP TABLE ops.alerts; --", pd.DataFrame({"x": [1]}))


def test_read_table_accepts_known_table(tmp_path: Path) -> None:
    """A known-allowed table name must not raise ValueError."""
    store = DuckDBStore(tmp_path / "t.duckdb")
    # ops.alerts is a known allowed table — must not raise
    result = store.read_table("ops.alerts")
    assert isinstance(result, pd.DataFrame)


def test_replace_table_preserves_schema_when_empty_df(tmp_path: Path) -> None:
    """replace_table with empty DataFrame must not destroy the table schema."""
    store = DuckDBStore(tmp_path / "t2.duckdb")
    store.append_dataframe("ops.alerts", pd.DataFrame([{
        "alert_id": "a1", "user_id": "u1", "snapshot_date": "2026-01-01",
        "created_at": "2026-01-01T00:00:00+00:00", "risk_level": "high",
        "status": "open", "prediction_id": "p1", "report_path": None,
    }]))
    empty_df = pd.DataFrame(columns=["alert_id", "user_id", "snapshot_date", "created_at", "risk_level", "status", "prediction_id", "report_path"])
    store.replace_table("ops.alerts", empty_df)
    # Schema must survive — can still insert a row
    store.append_dataframe("ops.alerts", pd.DataFrame([{
        "alert_id": "a2", "user_id": "u2", "snapshot_date": "2026-01-02",
        "created_at": "2026-01-01T00:00:00+00:00", "risk_level": "medium",
        "status": "open", "prediction_id": "p2", "report_path": None,
    }]))
    result = store.fetch_df("SELECT COUNT(*) AS n FROM ops.alerts")
    assert result.iloc[0]["n"] == 1  # only a2 (replace_table cleared a1)


def test_transaction_is_atomic_on_error(tmp_path: Path) -> None:
    """If any statement in a transaction raises, all changes are rolled back."""
    store = DuckDBStore(tmp_path / "t3.duckdb")
    try:
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO ops.alerts (alert_id, user_id, snapshot_date, created_at, risk_level, status) VALUES ('atomic_test', 'u1', '2026-01-01', now(), 'high', 'open')"
            )
            raise RuntimeError("simulated failure")
    except RuntimeError:
        pass
    result = store.fetch_df("SELECT COUNT(*) AS n FROM ops.alerts WHERE alert_id = 'atomic_test'")
    assert result.iloc[0]["n"] == 0, "Transaction must have been rolled back"


# ── Column name validation (refresh_live._safe_column_name) ──────────────────

from pipeline.refresh_live import _safe_column_name


@pytest.mark.parametrize("bad_col", [
    "x; DROP TABLE foo; --",
    "a b",
    "1abc",
    "-col",
])
def test_safe_column_name_rejects_invalid(bad_col):
    with pytest.raises(ValueError, match="invalid characters"):
        _safe_column_name(bad_col)


@pytest.mark.parametrize("good_col", [
    "user_id",
    "fiat_in_30d",
    "_private",
])
def test_safe_column_name_accepts_valid(good_col):
    assert _safe_column_name(good_col) == good_col
