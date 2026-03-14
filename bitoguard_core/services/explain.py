from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import load_settings
from models.common import encode_features, feature_columns, load_feature_table, load_lgbm


def _resolve_model_path(settings, model_version: str | None) -> Path | None:
    models_dir = settings.artifact_dir / "models"
    if model_version:
        exact_path = models_dir / f"{model_version}.lgbm"
        if exact_path.exists():
            return exact_path

    model_files = sorted(models_dir.glob("lgbm_*.lgbm"))
    if not model_files:
        return None
    return model_files[-1]


def explain_user(
    user_id: str,
    *,
    snapshot_date: object | None = None,
    model_version: str | None = None,
) -> list[dict]:
    import shap

    settings = load_settings()
    features = load_feature_table("features.feature_snapshots_user_day")
    if features.empty:
        return []

    target_date = features["snapshot_date"].max() if snapshot_date is None else pd.Timestamp(snapshot_date)
    frame = features[(features["snapshot_date"] == target_date) & (features["user_id"] == user_id)].copy()
    if frame.empty:
        return []

    model_path = _resolve_model_path(settings, model_version)
    if model_path is None:
        return []

    meta_path = model_path.with_suffix(".json")
    if not meta_path.exists():
        return []

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    model = load_lgbm(model_path)
    cols = feature_columns(frame)
    encoded, encoded_columns = encode_features(frame, cols, reference_columns=meta["encoded_columns"])
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(encoded)
    if isinstance(shap_values, list):
        shap_frame = pd.DataFrame(shap_values[-1], columns=encoded_columns)
    else:
        shap_frame = pd.DataFrame(shap_values, columns=encoded_columns)
    if shap_frame.empty:
        return []

    factors = pd.DataFrame({
        "feature": encoded_columns,
        "value": encoded.iloc[0].tolist(),
        "impact": shap_frame.iloc[0].tolist(),
    })
    factors["abs_impact"] = factors["impact"].abs()
    top = factors.sort_values("abs_impact", ascending=False).head(10)
    return top[["feature", "value", "impact"]].to_dict(orient="records")
