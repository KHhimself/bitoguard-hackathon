"""Tests for build_features_v2 EXPORT_TO_S3 env var wiring (F3)."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _empty_df():
    return pd.DataFrame({"user_id": []})


def _run_build_v2(export_env: str):
    """Helper: run build_v2() with mocked dependencies."""
    empty = _empty_df()

    old = os.environ.get("EXPORT_TO_S3")
    try:
        if export_env:
            os.environ["EXPORT_TO_S3"] = export_env
        elif "EXPORT_TO_S3" in os.environ:
            del os.environ["EXPORT_TO_S3"]

        # Import after env var is set so os.environ.get() in build_v2 reads it correctly.
        import importlib
        import features.build_features_v2 as bfv2
        importlib.reload(bfv2)

        with patch.object(bfv2, "load_settings") as mock_settings, \
             patch.object(bfv2, "DuckDBStore") as mock_store_cls, \
             patch.object(bfv2, "build_and_store_v2_features") as mock_build:
            mock_settings.return_value.db_path = "/tmp/fake.duckdb"
            mock_store = MagicMock()
            mock_store.read_table.return_value = empty
            mock_store_cls.return_value = mock_store
            mock_build.return_value = empty

            bfv2.build_v2()

            return mock_build.call_args
    finally:
        if old is None:
            os.environ.pop("EXPORT_TO_S3", None)
        else:
            os.environ["EXPORT_TO_S3"] = old


def test_export_to_s3_true_when_env_set():
    """F3: export_to_s3=True is passed when EXPORT_TO_S3=true."""
    call = _run_build_v2("true")
    kwargs = call[1] if call else {}
    assert kwargs.get("export_to_s3") is True, f"expected export_to_s3=True, got {kwargs}"


def test_export_to_s3_false_when_env_unset():
    """F3: export_to_s3=False when EXPORT_TO_S3 is unset."""
    call = _run_build_v2("")
    kwargs = call[1] if call else {}
    assert kwargs.get("export_to_s3") is False, f"expected export_to_s3=False, got {kwargs}"
