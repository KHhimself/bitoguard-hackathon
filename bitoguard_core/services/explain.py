from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from config import load_settings
from models.common import encode_features, feature_columns, load_feature_table, load_joblib, load_lgbm

_log = logging.getLogger(__name__)


def _resolve_model_path(settings, model_version: str | None) -> Path | None:
    """Resolve LightGBM model path for SHAP. Supports both native .lgbm and sklearn .joblib formats."""
    models_dir = settings.artifact_dir / "models"
    if model_version:
        for ext in (".lgbm", ".joblib"):
            p = models_dir / f"{model_version}{ext}"
            if p.exists():
                return p

    # Fall back to latest lgbm_v2 joblib, then native lgbm
    for pattern in ("lgbm_v2_*.joblib", "lgbm_*.lgbm"):
        model_files = sorted(models_dir.glob(pattern))
        if model_files:
            return model_files[-1]
    return None


def _load_lgbm_model(model_path: Path):
    """Load LightGBM model from either native .lgbm or sklearn .joblib format."""
    if model_path.suffix == ".joblib":
        return load_joblib(model_path)
    return load_lgbm(model_path)


def _load_model_meta(model_path: Path) -> dict:
    """Load metadata for a model file. Handles both native and stacker branch formats."""
    meta_path = model_path.with_suffix(".json")
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def explain_user(
    user_id: str,
    *,
    snapshot_date: object | None = None,
    model_version: str | None = None,
) -> list[dict]:
    import shap

    settings = load_settings()

    # Use v2 feature snapshots for stacker models, fall back to user_day
    features = load_feature_table("features.feature_snapshots_v2")
    if features.empty:
        features = load_feature_table("features.feature_snapshots_user_day")
    if features.empty:
        _log.warning("explain_user(%s): no feature snapshots found in v2 or user_day tables", user_id)
        return []

    snap_col = "snapshot_date" if "snapshot_date" in features.columns else None
    if snap_col:
        target_date = features[snap_col].max() if snapshot_date is None else pd.Timestamp(snapshot_date)
        frame = features[(features[snap_col] == target_date) & (features["user_id"] == user_id)].copy()
    else:
        frame = features[features["user_id"] == user_id].copy()
    if frame.empty:
        _log.warning("explain_user(%s): user not found in feature snapshot (snapshot_date=%s)", user_id, snapshot_date)
        return []

    model_path = _resolve_model_path(settings, model_version)
    if model_path is None:
        _log.warning("explain_user(%s): no LightGBM model found (model_version=%s)", user_id, model_version)
        return []

    meta = _load_model_meta(model_path)
    if not meta:
        _log.warning("explain_user(%s): model metadata missing for %s", user_id, model_path)
        return []

    model = _load_lgbm_model(model_path)
    cols = feature_columns(frame)
    ref_cols = meta.get("encoded_columns") or meta.get("feature_columns")
    if not ref_cols:
        _log.warning("explain_user(%s): model metadata has no feature column list (%s)", user_id, model_path)
        return []
    encoded, encoded_columns = encode_features(frame, cols, reference_columns=ref_cols)

    # Support both sklearn LGBMClassifier and native booster
    underlying = getattr(model, "booster_", model)
    explainer = shap.TreeExplainer(underlying)
    shap_values = explainer.shap_values(encoded)
    if isinstance(shap_values, list):
        shap_frame = pd.DataFrame(shap_values[-1], columns=encoded_columns)
    else:
        shap_frame = pd.DataFrame(shap_values, columns=encoded_columns)
    if shap_frame.empty:
        _log.warning("explain_user(%s): SHAP computation returned empty frame", user_id)
        return []

    factors = pd.DataFrame({
        "feature": encoded_columns,
        "value": encoded.iloc[0].tolist(),
        "impact": shap_frame.iloc[0].tolist(),
    })
    factors["abs_impact"] = factors["impact"].abs()
    top = factors.sort_values("abs_impact", ascending=False).head(10)
    return top[["feature", "value", "impact"]].to_dict(orient="records")
