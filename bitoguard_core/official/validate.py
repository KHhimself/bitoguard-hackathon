from __future__ import annotations

import json
from math import ceil

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score

from official.anomaly import score_anomaly_frame
from official.common import VALIDATION_THRESHOLDS, default_temporal_cutoff, encode_frame, feature_report_path, load_official_paths, load_pickle, save_json
from official.features import build_official_features
from official.graph_features import build_official_graph_features
from official.rules import evaluate_official_rules
from official.train import _load_dataset


def _load_latest_model() -> tuple[object, dict]:
    paths = load_official_paths()
    model_files = sorted(paths.model_dir.glob("official_lgbm_*.pkl"))
    if not model_files:
        raise FileNotFoundError("No official_lgbm model found")
    model_path = model_files[-1]
    meta = json.loads(model_path.with_suffix(".json").read_text(encoding="utf-8"))
    return load_pickle(model_path), meta


def _threshold_report(y_true: pd.Series, probabilities: np.ndarray) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for threshold in VALIDATION_THRESHOLDS:
        preds = (probabilities >= threshold).astype(int)
        rows.append(
            {
                "threshold": threshold,
                "precision": float(precision_score(y_true, preds, zero_division=0)),
                "recall": float(recall_score(y_true, preds, zero_division=0)),
                "f1": float(f1_score(y_true, preds, zero_division=0)),
            }
        )
    return rows


def _best_threshold(y_true: pd.Series, probabilities: np.ndarray) -> float:
    candidates = sorted(set([0.30, 0.50, 0.80] + [round(float(x), 4) for x in probabilities]))
    best_threshold = 0.5
    best_score = -1.0
    for threshold in candidates:
        preds = (probabilities >= threshold).astype(int)
        score = f1_score(y_true, preds, zero_division=0)
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
    return best_threshold


def _feature_importance(model: object, encoded_columns: list[str], top_k: int = 20) -> list[dict[str, float]]:
    importance = pd.DataFrame({"feature": encoded_columns, "importance": model.feature_importances_})
    importance = importance.sort_values("importance", ascending=False).head(top_k)
    return [
        {"feature": row["feature"], "importance": float(row["importance"])}
        for _, row in importance.iterrows()
    ]


def _temporal_stress_metrics(model: object, meta: dict, split_frame: pd.DataFrame) -> dict[str, float | str]:
    cutoff = default_temporal_cutoff()
    cutoff_tag = "temporal"
    full_features = build_official_features(cutoff_ts=cutoff, cutoff_tag=cutoff_tag)
    full_graph = build_official_graph_features(cutoff_ts=cutoff, cutoff_tag=cutoff_tag)
    stress = full_features.merge(full_graph, on=["user_id", "snapshot_cutoff_at", "snapshot_cutoff_tag"], how="left")
    anomaly = score_anomaly_frame(stress).drop(columns=["snapshot_cutoff_at", "snapshot_cutoff_tag"])
    stress = stress.merge(anomaly, on="user_id", how="left")
    stress = stress.merge(evaluate_official_rules(stress), on="user_id", how="left")
    test_ids = set(split_frame[split_frame["split"] == "test"]["user_id"].tolist())
    stress_test = stress[(stress["cohort"] == "train_only") & (stress["user_id"].isin(test_ids))].copy()
    x_test, _ = encode_frame(stress_test, meta["feature_columns"], reference_columns=meta["encoded_columns"])
    probabilities = model.predict_proba(x_test)[:, 1]
    preds = (probabilities >= meta["selected_threshold"]).astype(int)
    y_true = stress_test["status"].astype(int)
    return {
        "cutoff_at": cutoff.isoformat(),
        "precision": float(precision_score(y_true, preds, zero_division=0)),
        "recall": float(recall_score(y_true, preds, zero_division=0)),
        "f1": float(f1_score(y_true, preds, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, probabilities)),
    }


def _shadow_report(dataset: pd.DataFrame, model: object, meta: dict) -> dict[str, object]:
    shadow = dataset[dataset["cohort"] == "shadow_overlap"].copy()
    x_shadow, _ = encode_frame(shadow, meta["feature_columns"], reference_columns=meta["encoded_columns"])
    probabilities = model.predict_proba(x_shadow)[:, 1]
    shadow["model_probability"] = probabilities
    shadow = shadow.sort_values("model_probability", ascending=False).reset_index(drop=True)
    decile_size = max(1, ceil(len(shadow) * 0.1))
    top_decile = shadow.head(decile_size)
    report = {
        "shadow_rows": int(len(shadow)),
        "positive_rate": float(shadow["status"].mean()),
        "top_decile_size": int(decile_size),
        "top_decile_positive_rate": float(top_decile["status"].mean()),
        "top_decile_hit_rate": float(top_decile["status"].sum() / max(1, shadow["status"].sum())),
        "score_summary": {
            "min": float(shadow["model_probability"].min()),
            "p50": float(shadow["model_probability"].median()),
            "p90": float(shadow["model_probability"].quantile(0.9)),
            "max": float(shadow["model_probability"].max()),
        },
    }
    save_json(report, feature_report_path("official_shadow_report.json"))
    return report


def validate_official_model() -> dict[str, object]:
    dataset = _load_dataset("full")
    model, meta = _load_latest_model()
    split_frame = pd.read_parquet(meta["split_path"])
    valid_ids = set(split_frame[split_frame["split"] == "valid"]["user_id"].tolist())
    test_ids = set(split_frame[split_frame["split"] == "test"]["user_id"].tolist())

    valid = dataset[(dataset["cohort"] == "train_only") & (dataset["user_id"].isin(valid_ids))].copy()
    test = dataset[(dataset["cohort"] == "train_only") & (dataset["user_id"].isin(test_ids))].copy()

    x_valid, _ = encode_frame(valid, meta["feature_columns"], reference_columns=meta["encoded_columns"])
    x_test, _ = encode_frame(test, meta["feature_columns"], reference_columns=meta["encoded_columns"])
    valid_prob = model.predict_proba(x_valid)[:, 1]
    test_prob = model.predict_proba(x_test)[:, 1]
    selected_threshold = _best_threshold(valid["status"].astype(int), valid_prob)
    test_pred = (test_prob >= selected_threshold).astype(int)

    y_true = test["status"].astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, test_pred).ravel()
    report = {
        "model_version": meta["model_version"],
        "selected_threshold": selected_threshold,
        "precision": float(precision_score(y_true, test_pred, zero_division=0)),
        "recall": float(recall_score(y_true, test_pred, zero_division=0)),
        "f1": float(f1_score(y_true, test_pred, zero_division=0)),
        "fpr": float(fp / max(1, fp + tn)),
        "average_precision": float(average_precision_score(y_true, test_prob)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "threshold_sensitivity": _threshold_report(y_true, test_prob),
        "feature_importance": _feature_importance(model, meta["encoded_columns"]),
    }
    meta["selected_threshold"] = selected_threshold
    save_json(meta, load_official_paths().model_dir / f"{meta['model_version']}.json")
    report["temporal_stress_test"] = _temporal_stress_metrics(model, meta, split_frame)
    report["shadow_diagnostics"] = _shadow_report(dataset, model, meta)
    save_json(report, feature_report_path("official_validation_report.json"))
    return report


def main() -> None:
    print(validate_official_model())


if __name__ == "__main__":
    main()
