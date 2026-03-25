from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from official.runtime import (
    build_alert_report,
    build_graph_payload,
    build_user_360,
    get_model_metrics,
    get_stats as get_official_stats,
    get_threshold_metrics,
    list_alerts as list_official_alerts,
)


app = FastAPI(title="BitoGuard Core API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _raise_runtime_error(exc: FileNotFoundError) -> HTTPException:
    return HTTPException(status_code=503, detail=f"official runtime artifact missing: {exc}")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/alerts")
def list_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    risk_level: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    try:
        return list_official_alerts(page=page, page_size=page_size, risk_level=risk_level, status=status)
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/alerts/{alert_id}/report")
def alert_report(alert_id: str) -> dict[str, Any]:
    try:
        return build_alert_report(alert_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="alert not found") from exc
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/users/{user_id}/360")
def user_360(user_id: str) -> dict[str, Any]:
    try:
        return build_user_360(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/users/{user_id}/graph")
def user_graph(user_id: str, max_hops: int = Query(default=2, ge=1, le=2)) -> dict[str, Any]:
    try:
        return build_graph_payload(user_id, max_hops=max_hops)
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/stats")
def stats() -> dict[str, Any]:
    try:
        return get_official_stats()
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/metrics/model")
def model_metrics() -> dict[str, Any]:
    try:
        return get_model_metrics()
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc


@app.get("/metrics/threshold")
def threshold_metrics() -> list[dict[str, Any]]:
    try:
        return get_threshold_metrics()
    except FileNotFoundError as exc:
        raise _raise_runtime_error(exc) from exc
