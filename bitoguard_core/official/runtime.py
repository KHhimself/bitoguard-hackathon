from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from official.bundle import load_selected_bundle
from official.common import feature_output_path, load_clean_table, load_official_paths, load_pickle
from official.features import build_official_features
from official.graph_features import build_official_graph_features
from official.pipeline import run_official_pipeline
from official.rules import RULE_DEFINITIONS
from official.score import score_official_predict
from official.train import _load_dataset, train_official_model
from official.validate import validate_official_model


FEATURE_LABELS_ZH = {
    "twd_total_sum": "台幣總流量",
    "twd_total_count": "台幣交易次數",
    "twd_withdraw_sum": "台幣出金總額",
    "crypto_total_sum": "虛幣總流量",
    "crypto_total_count": "虛幣交易次數",
    "crypto_withdraw_sum": "虛幣出金總額",
    "shared_ip_user_count": "共享 IP 關聯用戶數",
    "shared_wallet_user_count": "共享錢包關聯用戶數",
    "wallet_component_size": "錢包關聯群體規模",
    "ip_component_size": "IP 關聯群體規模",
    "relation_unique_counterparty_count": "內轉唯一對手數",
    "relation_degree_centrality": "內轉關聯中心性",
    "trade_night_ratio": "深夜交易比例",
    "trade_market_ratio": "市價交易比例",
    "trade_intraday_concentration": "日內交易集中度",
    "fast_cashout_24h_count": "24 小時快速出金次數",
    "fast_cashout_72h_count": "72 小時快速出金次數",
    "analyst_risk_score": "綜合風險分數",
    "rule_score": "規則風險分數",
    "anomaly_score": "異常分數",
}

ALERT_ID_PREFIX = "official_alert_"
PREDICTION_FILE_NAME = "official_predict_scores.parquet"
VALIDATION_REPORT_NAME = "official_validation_report.json"


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in record.items()}


def _normalize_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_normalize_record(record) for record in frame.to_dict(orient="records")]


def _normalize_user_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _alert_id_for_user(user_id: Any) -> str:
    return f"{ALERT_ID_PREFIX}{_normalize_user_id(user_id)}"


def _user_id_from_alert_id(alert_id: str) -> str:
    if alert_id.startswith(ALERT_ID_PREFIX):
        return alert_id[len(ALERT_ID_PREFIX):]
    return alert_id


def _paths() -> Any:
    return load_official_paths()


def ensure_runtime_artifacts() -> None:
    paths = _paths()
    user_feature_path = feature_output_path("official_user_features", "full")
    graph_feature_path = feature_output_path("official_graph_features", "full")
    bundle_path = paths.bundle_path
    prediction_path = paths.prediction_dir / PREDICTION_FILE_NAME
    validation_path = paths.report_dir / VALIDATION_REPORT_NAME

    if not user_feature_path.exists():
        build_official_features(cutoff_tag="full")
    if not graph_feature_path.exists():
        build_official_graph_features(cutoff_tag="full")
    if prediction_path.exists() and validation_path.exists() and bundle_path.exists():
        return

    try:
        if not bundle_path.exists():
            train_official_model()
        try:
            load_selected_bundle(require_ready=True)
        except (FileNotFoundError, ValueError):
            validate_official_model()
        if not validation_path.exists():
            validate_official_model()
        if not prediction_path.exists():
            score_official_predict()
    except Exception:
        run_official_pipeline()


def _load_user_info() -> pd.DataFrame:
    frame = load_clean_table("user_info").copy()
    frame["user_id"] = frame["user_id"].map(_normalize_user_id)
    return frame


def _load_user_index() -> pd.DataFrame:
    frame = load_clean_table("user_index").copy()
    frame["user_id"] = frame["user_id"].map(_normalize_user_id)
    return frame


def _load_user_features() -> pd.DataFrame:
    ensure_runtime_artifacts()
    frame = pd.read_parquet(feature_output_path("official_user_features", "full"))
    frame["user_id"] = frame["user_id"].map(_normalize_user_id)
    return frame


def _load_graph_features() -> pd.DataFrame:
    ensure_runtime_artifacts()
    frame = pd.read_parquet(feature_output_path("official_graph_features", "full"))
    frame["user_id"] = frame["user_id"].map(_normalize_user_id)
    return frame


def _load_predictions() -> pd.DataFrame:
    ensure_runtime_artifacts()
    prediction_path = _paths().prediction_dir / PREDICTION_FILE_NAME
    predictions = pd.read_parquet(prediction_path).copy()
    predictions["user_id"] = predictions["user_id"].map(_normalize_user_id)

    features = _load_user_features()[["user_id", "snapshot_cutoff_at", "snapshot_cutoff_tag"]].copy()
    merged = predictions.merge(features, on="user_id", how="left")
    merged["alert_id"] = merged["user_id"].map(_alert_id_for_user)
    merged["status"] = "open"
    merged["created_at"] = pd.to_datetime(merged["snapshot_cutoff_at"], utc=True, errors="coerce")
    merged["risk_score"] = pd.to_numeric(merged["analyst_risk_score"], errors="coerce")
    merged["submission_probability"] = pd.to_numeric(merged["submission_probability"], errors="coerce")
    merged["risk_rank"] = pd.to_numeric(merged["risk_rank"], errors="coerce")
    return merged


def list_alerts(
    *,
    page: int,
    page_size: int,
    risk_level: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    alerts = _load_predictions()
    if risk_level is not None:
        alerts = alerts[alerts["risk_level"] == risk_level].copy()
    if status is not None:
        alerts = alerts[alerts["status"] == status].copy()

    alerts = alerts.sort_values(["risk_rank", "risk_score"], ascending=[True, False], na_position="last")
    total = len(alerts)
    start = (page - 1) * page_size
    items = alerts.iloc[start:start + page_size][[
        "alert_id",
        "user_id",
        "risk_level",
        "risk_score",
        "status",
        "created_at",
    ]].copy()
    return {
        "items": _normalize_records(items),
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": start + page_size < total,
    }


def _lookup_alert(alert_id: str) -> pd.Series:
    alerts = _load_predictions()
    row = alerts[alerts["alert_id"] == alert_id].copy()
    if row.empty:
        row = alerts[alerts["user_id"] == _user_id_from_alert_id(alert_id)].copy()
    if row.empty:
        raise KeyError(alert_id)
    return row.sort_values(["risk_rank", "risk_score"], ascending=[True, False]).iloc[0]


def _feature_label_zh(feature_name: str) -> str:
    if feature_name in FEATURE_LABELS_ZH:
        return FEATURE_LABELS_ZH[feature_name]
    return feature_name.replace("_", " ")


_SIGNAL_LABELS_ZH = {
    "base_a_probability": "CatBoost 主模型",
    "base_b_probability": "CatBoost 輔模型",
    "base_c_probability": "GraphSAGE 圖模型",
    "base_d_probability": "LightGBM 模型",
    "base_e_probability": "XGBoost 模型",
    "anomaly_score": "異常偵測分數",
    "rule_score": "規則引擎分數",
    "stacker_raw_probability": "Stacker 原始機率",
}


def explain_user(user_id: str) -> list[dict[str, Any]]:
    """Return model signal breakdown for a user from prediction scores."""
    ensure_runtime_artifacts()
    predictions = _load_predictions()
    row = predictions[predictions["user_id"] == user_id]
    if row.empty:
        return []
    record = row.iloc[0]

    signal_columns = [
        "base_a_probability", "base_b_probability", "base_c_probability",
        "anomaly_score", "rule_score",
    ]
    factors = []
    for col in signal_columns:
        value = float(record.get(col, 0) or 0)
        if value == 0:
            continue
        factors.append({
            "feature": col,
            "feature_zh": _SIGNAL_LABELS_ZH.get(col, _feature_label_zh(col)),
            "impact": value,
            "value": round(value, 4),
        })
    factors.sort(key=lambda f: abs(f["impact"]), reverse=True)
    return factors[:6]


def _recent_timeline(user_id: str) -> list[dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    twd = load_clean_table("twd_transfer")
    twd = twd[twd["user_id"].map(_normalize_user_id) == user_id][["created_at", "amount_twd", "kind_label"]].copy()
    if not twd.empty:
        twd["time"] = pd.to_datetime(twd["created_at"], utc=True, errors="coerce")
        twd["type"] = twd["kind_label"].map(lambda value: f"twd_{value}")
        twd["amount"] = pd.to_numeric(twd["amount_twd"], errors="coerce")
        frames.append(twd[["time", "type", "amount"]])

    crypto = load_clean_table("crypto_transfer")
    crypto = crypto[crypto["user_id"].map(_normalize_user_id) == user_id][["created_at", "amount_twd_equiv", "kind_label"]].copy()
    if not crypto.empty:
        crypto["time"] = pd.to_datetime(crypto["created_at"], utc=True, errors="coerce")
        crypto["type"] = crypto["kind_label"].map(lambda value: f"crypto_{value}")
        crypto["amount"] = pd.to_numeric(crypto["amount_twd_equiv"], errors="coerce")
        frames.append(crypto[["time", "type", "amount"]])

    trading = load_clean_table("usdt_twd_trading")
    trading = trading[trading["user_id"].map(_normalize_user_id) == user_id][["updated_at", "trade_notional_twd", "side_label"]].copy()
    if not trading.empty:
        trading["time"] = pd.to_datetime(trading["updated_at"], utc=True, errors="coerce")
        trading["type"] = trading["side_label"].map(lambda value: f"trade_{value}")
        trading["amount"] = pd.to_numeric(trading["trade_notional_twd"], errors="coerce")
        frames.append(trading[["time", "type", "amount"]])

    if not frames:
        return []

    timeline = pd.concat(frames, ignore_index=True).dropna(subset=["time"]).sort_values("time", ascending=False).head(10)
    return [
        {
            "time": record["time"].isoformat(),
            "type": record["type"],
            "amount": None if pd.isna(record["amount"]) else float(record["amount"]),
        }
        for record in timeline.to_dict(orient="records")
    ]


def _recommended_action(alert: pd.Series, user_index_row: pd.Series | None) -> str:
    if user_index_row is not None and bool(user_index_row.get("is_known_blacklist", False)):
        return "hold_withdrawal"
    if alert["risk_level"] == "critical":
        return "hold_withdrawal"
    if alert["risk_level"] == "high":
        return "manual_review"
    return "monitor"


def build_alert_report(alert_id: str) -> dict[str, Any]:
    alert = _lookup_alert(alert_id)
    user_id = alert["user_id"]

    features = _load_user_features()
    feature_row = features[features["user_id"] == user_id]
    graph_features = _load_graph_features()
    graph_row = graph_features[graph_features["user_id"] == user_id]
    user_index = _load_user_index()
    user_index_row = user_index[user_index["user_id"] == user_id]

    feature = feature_row.iloc[0] if not feature_row.empty else None
    graph_feature = graph_row.iloc[0] if not graph_row.empty else None
    index_record = user_index_row.iloc[0] if not user_index_row.empty else None

    rule_codes: list[str] = []
    if alert.get("top_reason_codes"):
        try:
            rule_codes = json.loads(alert["top_reason_codes"])
        except json.JSONDecodeError:
            rule_codes = []

    risk_score = float(alert["risk_score"]) if not pd.isna(alert["risk_score"]) else 0.0
    rule_hits = [{"code": code, "label_zh": RULE_DEFINITIONS.get(code, code)} for code in rule_codes]
    recommended_action = _recommended_action(alert, index_record)
    summary_reason = "、".join(hit["label_zh"] for hit in rule_hits[:3]) if rule_hits else "模型綜合風險分數偏高"

    return {
        "user_id": user_id,
        "summary_zh": f"用戶 {user_id} 目前風險等級為 {alert['risk_level']}，綜合風險分數 {risk_score:.2f}，主要訊號包含 {summary_reason}。",
        "alert": _normalize_record({
            "alert_id": alert["alert_id"],
            "user_id": user_id,
            "risk_level": alert["risk_level"],
            "risk_score": risk_score,
            "status": alert["status"],
            "created_at": alert["created_at"],
        }),
        "case": None,
        "case_actions": [],
        "allowed_decisions": [],
        "risk_summary": {
            "risk_score": risk_score,
            "risk_level": alert["risk_level"],
            "prediction_time": _normalize_value(alert["created_at"]),
        },
        "shap_top_factors": explain_user(user_id),
        "rule_hits": rule_hits,
        "graph_evidence": {
            "shared_ip_user_count": int(graph_feature["shared_ip_user_count"]) if graph_feature is not None else 0,
            "shared_wallet_user_count": int(graph_feature["shared_wallet_user_count"]) if graph_feature is not None else 0,
            "relation_component_size": int(graph_feature["relation_component_size"]) if graph_feature is not None else 1,
            "relation_out_degree": int(graph_feature["relation_out_degree"]) if graph_feature is not None else 0,
        },
        "timeline_summary": _recent_timeline(user_id),
        "recommended_action": recommended_action,
        "latest_features": None if feature is None else _normalize_record(feature.to_dict()),
    }


def build_user_360(user_id: str) -> dict[str, Any]:
    normalized_user_id = _normalize_user_id(user_id)
    user_info = _load_user_info()
    user_index = _load_user_index()
    profile = user_info.merge(
        user_index[["user_id", "status", "is_known_blacklist", "needs_prediction", "has_profile"]],
        on="user_id",
        how="left",
    )
    user_row = profile[profile["user_id"] == normalized_user_id]
    if user_row.empty:
        raise KeyError(user_id)

    alerts = _load_predictions()
    alert_row = alerts[alerts["user_id"] == normalized_user_id].copy()
    prediction_payload = None
    if not alert_row.empty:
        latest_alert = alert_row.sort_values(["risk_rank", "risk_score"], ascending=[True, False]).iloc[0]
        prediction_payload = _normalize_record({
            "user_id": normalized_user_id,
            "risk_level": latest_alert["risk_level"],
            "risk_score": latest_alert["risk_score"],
            "submission_probability": latest_alert["submission_probability"],
            "snapshot_date": latest_alert["snapshot_cutoff_at"],
            "alert_id": latest_alert["alert_id"],
        })

    features = _load_user_features()
    feature_row = features[features["user_id"] == normalized_user_id]
    latest_features = None if feature_row.empty else _normalize_record(feature_row.iloc[0].to_dict())

    source_ip_frames: list[pd.DataFrame] = []
    for table_name, time_column, source_label, type_column in (
        ("twd_transfer", "created_at", "twd_transfer", "kind_label"),
        ("crypto_transfer", "created_at", "crypto_transfer", "kind_label"),
        ("usdt_twd_trading", "updated_at", "usdt_twd_trading", "side_label"),
    ):
        frame = load_clean_table(table_name)
        frame["user_id"] = frame["user_id"].map(_normalize_user_id)
        subset = frame[frame["user_id"] == normalized_user_id].copy()
        if subset.empty or "source_ip_hash" not in subset.columns:
            continue
        subset["occurred_at"] = pd.to_datetime(subset[time_column], utc=True, errors="coerce")
        subset["ip_address"] = subset["source_ip_hash"]
        subset["event_source"] = source_label
        subset["event_type"] = subset[type_column] if type_column in subset.columns else None
        source_ip_frames.append(subset[["occurred_at", "ip_address", "event_source", "event_type"]])

    recent_source_ip_events: list[dict[str, Any]] = []
    if source_ip_frames:
        source_ip_frame = pd.concat(source_ip_frames, ignore_index=True).dropna(subset=["occurred_at"])
        source_ip_frame = source_ip_frame.sort_values("occurred_at", ascending=False).head(10)
        recent_source_ip_events = _normalize_records(source_ip_frame)

    crypto = load_clean_table("crypto_transfer")
    crypto["user_id"] = crypto["user_id"].map(_normalize_user_id)
    recent_crypto = crypto[crypto["user_id"] == normalized_user_id].copy()
    recent_crypto["occurred_at"] = pd.to_datetime(recent_crypto["created_at"], utc=True, errors="coerce")
    recent_crypto["direction"] = recent_crypto["kind_label"]
    recent_crypto["counterparty_wallet_id"] = recent_crypto["to_wallet_hash"].fillna(recent_crypto["from_wallet_hash"])
    recent_crypto = recent_crypto.sort_values("occurred_at", ascending=False).head(10)

    return {
        "user": _normalize_record(user_row.iloc[0].to_dict()),
        "latest_prediction": prediction_payload,
        "latest_features": latest_features,
        "recent_source_ip_events": recent_source_ip_events,
        "recent_crypto_transactions": _normalize_records(
            recent_crypto[["occurred_at", "direction", "amount_twd_equiv", "counterparty_wallet_id"]]
        ),
    }


def build_graph_payload(user_id: str, max_hops: int) -> dict[str, Any]:
    normalized_user_id = _normalize_user_id(user_id)
    focus_node_id = f"user:{normalized_user_id}"

    ip_frames: list[pd.DataFrame] = []
    for table_name, column in (
        ("twd_transfer", "source_ip_hash"),
        ("crypto_transfer", "source_ip_hash"),
        ("usdt_twd_trading", "source_ip_hash"),
    ):
        frame = load_clean_table(table_name)
        frame["user_id"] = frame["user_id"].map(_normalize_user_id)
        subset = frame[["user_id", column]].rename(columns={column: "entity_id"}).copy()
        subset["entity_type"] = "ip"
        subset["relation_type"] = "login_from_ip"
        ip_frames.append(subset)
    ip_edges = pd.concat(ip_frames, ignore_index=True)

    crypto = load_clean_table("crypto_transfer")
    crypto["user_id"] = crypto["user_id"].map(_normalize_user_id)
    wallet_edges = pd.concat(
        [
            crypto[["user_id", "from_wallet_hash"]].rename(columns={"from_wallet_hash": "entity_id"}),
            crypto[["user_id", "to_wallet_hash"]].rename(columns={"to_wallet_hash": "entity_id"}),
        ],
        ignore_index=True,
    )
    wallet_edges["entity_type"] = "wallet"
    wallet_edges["relation_type"] = "crypto_transfer_to_wallet"

    edge_frame = pd.concat([ip_edges, wallet_edges], ignore_index=True)
    edge_frame = edge_frame[edge_frame["entity_id"].notna() & edge_frame["user_id"].ne("")].drop_duplicates().copy()
    edge_frame["user_node"] = edge_frame["user_id"].map(lambda value: f"user:{value}")
    edge_frame["entity_node"] = edge_frame.apply(lambda row: f"{row['entity_type']}:{row['entity_id']}", axis=1)

    if focus_node_id not in set(edge_frame["user_node"]):
        return {
            "focus_user_id": normalized_user_id,
            "summary": {
                "node_count": 1,
                "edge_count": 0,
                "blacklist_neighbor_count": 0,
                "high_risk_neighbor_count": 0,
                "is_truncated": False,
            },
            "nodes": [{
                "id": focus_node_id,
                "type": "user",
                "label": normalized_user_id,
                "hop": 0,
                "is_focus": True,
                "risk_level": None,
                "is_known_blacklist": False,
            }],
            "edges": [],
        }

    adjacency: dict[str, set[str]] = {}
    for _, row in edge_frame.iterrows():
        adjacency.setdefault(row["user_node"], set()).add(row["entity_node"])
        adjacency.setdefault(row["entity_node"], set()).add(row["user_node"])

    distances = {focus_node_id: 0}
    queue = [focus_node_id]
    while queue:
        current = queue.pop(0)
        if distances[current] >= max_hops:
            continue
        for neighbor in sorted(adjacency.get(current, set())):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)

    included_nodes = set(distances)
    sub_edges = edge_frame[
        edge_frame["user_node"].isin(included_nodes)
        & edge_frame["entity_node"].isin(included_nodes)
    ].copy()

    predictions = _load_predictions()[["user_id", "risk_level"]].drop_duplicates(subset=["user_id"])
    risk_map = dict(zip(predictions["user_id"], predictions["risk_level"], strict=False))
    user_index = _load_user_index()
    blacklist_users = set(user_index[user_index["is_known_blacklist"].fillna(False)]["user_id"].tolist())

    node_records: list[dict[str, Any]] = []
    for node_id, hop in sorted(distances.items(), key=lambda item: (item[1], item[0])):
        node_type, raw_label = node_id.split(":", 1)
        node_records.append({
            "id": node_id,
            "type": node_type,
            "label": raw_label if node_type == "user" else raw_label[:12],
            "hop": hop,
            "is_focus": node_id == focus_node_id,
            "risk_level": risk_map.get(raw_label) if node_type == "user" else None,
            "is_known_blacklist": node_type == "user" and raw_label in blacklist_users,
        })

    original_node_count = len(node_records)
    if len(node_records) > 120:
        keep_ids = {record["id"] for record in node_records[:120]}
        keep_ids.add(focus_node_id)
        node_records = [record for record in node_records if record["id"] in keep_ids]
        sub_edges = sub_edges[
            sub_edges["user_node"].isin(keep_ids)
            & sub_edges["entity_node"].isin(keep_ids)
        ].copy()

    edge_records = [
        {
            "id": f"edge_{idx}",
            "source": row["user_node"],
            "target": row["entity_node"],
            "relation_type": row["relation_type"],
        }
        for idx, row in enumerate(sub_edges.to_dict(orient="records"), start=1)
    ]
    original_edge_count = len(edge_records)
    if len(edge_records) > 240:
        edge_records = edge_records[:240]

    used_node_ids = {focus_node_id}
    for edge in edge_records:
        used_node_ids.add(edge["source"])
        used_node_ids.add(edge["target"])
    final_nodes = [record for record in node_records if record["id"] in used_node_ids]

    return {
        "focus_user_id": normalized_user_id,
        "summary": {
            "node_count": len(final_nodes),
            "edge_count": len(edge_records),
            "blacklist_neighbor_count": sum(
                1 for node in final_nodes if node["type"] == "user" and not node["is_focus"] and node["is_known_blacklist"]
            ),
            "high_risk_neighbor_count": sum(
                1
                for node in final_nodes
                if node["type"] == "user" and not node["is_focus"] and node["risk_level"] in {"high", "critical"}
            ),
            "is_truncated": original_node_count > 120 or original_edge_count > 240,
        },
        "nodes": final_nodes,
        "edges": edge_records,
    }


def get_model_metrics() -> dict[str, Any]:
    ensure_runtime_artifacts()
    report_path = _paths().report_dir / VALIDATION_REPORT_NAME
    report = json.loads(report_path.read_text(encoding="utf-8"))
    calibrator = report["calibrator"]
    selected = calibrator["selected_row"]
    threshold_rows = [
        {
            "threshold": float(row["threshold"]),
            "precision": float(row["precision"]),
            "recall": float(row["recall"]),
            "f1": float(row["f1"]),
        }
        for row in calibrator["threshold_report"]["rows"]
    ]
    threshold_rows.sort(key=lambda row: row["threshold"])
    return {
        "model_version": report["bundle_version"],
        "precision": float(selected["precision"]),
        "recall": float(selected["recall"]),
        "f1": float(selected["f1"]),
        "fpr": float(selected["fpr"]),
        "average_precision": float(calibrator["average_precision"]),
        "confusion_matrix": {
            "tp": int(selected["tp"]),
            "fp": int(selected["fp"]),
            "tn": int(selected["tn"]),
            "fn": int(selected["fn"]),
        },
        "threshold_sensitivity": threshold_rows,
        "scenario_breakdown": [],
    }


def get_threshold_metrics() -> list[dict[str, Any]]:
    return get_model_metrics()["threshold_sensitivity"]


_HISTOGRAM_FILLS = [
    "#24D164", "#24D164", "#7CE08A", "#FFE066", "#FFB020",
    "#FF9A3C", "#FF6B4A", "#FF3B5C", "#E01E5A", "#B5144A",
]


def get_stats() -> dict[str, Any]:
    ensure_runtime_artifacts()
    predictions = _load_predictions()

    total = len(predictions)
    level_counts = predictions["risk_level"].value_counts().to_dict()
    for level in ("low", "medium", "high", "critical"):
        level_counts.setdefault(level, 0)

    scores = pd.to_numeric(predictions["risk_score"], errors="coerce").dropna()
    bins = list(range(0, 110, 10))
    labels = [f"{lo}-{hi}" for lo, hi in zip(bins[:-1], bins[1:])]
    histogram = pd.cut(scores, bins=bins, labels=labels, right=False).value_counts().sort_index()
    risk_score_histogram = [
        {"range": label, "count": int(histogram.get(label, 0)), "fill": _HISTOGRAM_FILLS[i]}
        for i, label in enumerate(labels)
    ]

    metrics = get_model_metrics()

    return {
        "total_users": total,
        "risk_level_counts": {k: int(v) for k, v in level_counts.items()},
        "risk_score_histogram": risk_score_histogram,
        "model_metrics_summary": {
            "f1": metrics["f1"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "average_precision": metrics["average_precision"],
        },
    }
