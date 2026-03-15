"""Tests for POST /pipeline/run endpoint (F5)."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

FAKE_ARN = "arn:aws:states:us-west-2:123456789012:stateMachine:bitoguard-prod-ml-pipeline"
FAKE_EXEC_ARN = "arn:aws:states:us-west-2:123456789012:execution:bitoguard-prod-ml-pipeline:test-run"


def _mock_sfn():
    mock = MagicMock()
    mock.start_execution.return_value = {"executionArn": FAKE_EXEC_ARN}
    return mock


def test_pipeline_run_returns_execution_arn(monkeypatch):
    """F5: POST /pipeline/run returns execution_arn from Step Functions."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    with patch("boto3.client", return_value=_mock_sfn()):
        resp = client.post("/pipeline/run", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert "execution_arn" in body
    assert body["execution_arn"] == FAKE_EXEC_ARN


def test_pipeline_run_passes_enable_tuning_false_by_default(monkeypatch):
    """F5: enable_tuning defaults to False in Step Functions input."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    mock_sfn = _mock_sfn()
    with patch("boto3.client", return_value=mock_sfn):
        client.post("/pipeline/run", json={})

    call_kwargs = mock_sfn.start_execution.call_args[1]
    payload = json.loads(call_kwargs["input"])
    assert payload["enable_tuning"] is False


def test_pipeline_run_passes_enable_tuning_true(monkeypatch):
    """F5: enable_tuning=True is forwarded to Step Functions."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    mock_sfn = _mock_sfn()
    with patch("boto3.client", return_value=mock_sfn):
        client.post("/pipeline/run", json={"enable_tuning": True})

    call_kwargs = mock_sfn.start_execution.call_args[1]
    payload = json.loads(call_kwargs["input"])
    assert payload["enable_tuning"] is True


def test_pipeline_run_missing_arn_env_returns_500(monkeypatch):
    """F5: returns 500 if BITOGUARD_STEP_FUNCTIONS_ARN is not set."""
    monkeypatch.delenv("BITOGUARD_STEP_FUNCTIONS_ARN", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    resp = client.post("/pipeline/run", json={})
    assert resp.status_code == 500
