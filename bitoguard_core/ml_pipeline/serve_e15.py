"""
SageMaker 推論伺服器 — E15 AML 管線。

Flask app（port 8080）：
  GET  /ping         → 健康檢查
  POST /invocations  → JSON/CSV → predictions

從 /opt/ml/model/ 載入 bundle + models。

Endpoint 模式下 C&S 不可用（需 63,770-node graph），退化方案：
  base_c_s_probability = base_a_probability
  base_c_probability   = 0（無 GraphSAGE）
"""
from __future__ import annotations

import io
import json
import os
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, Response, request

# ── 推論時也需要 import official 模組 ────────────────────────────────────────
# model.tar.gz 裡包含 code/ 子目錄（完整 bitoguard_core 原始碼）
_MODEL_DIR = Path(os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
_CODE_DIR = _MODEL_DIR / "code"
if _CODE_DIR.exists():
    sys.path.insert(0, str(_CODE_DIR))
sys.path.insert(0, "/opt/ml/code")

from official.bundle import load_selected_bundle  # noqa: E402
from official.common import load_pickle, encode_frame  # noqa: E402
from official.stacking import STACKER_FEATURE_COLUMNS, _add_base_meta_features  # noqa: E402

# ── 全域狀態 ──────────────────────────────────────────────────────────────────
_bundle: dict | None = None
_base_a_models: list = []
_base_e_models: list = []
_base_d_models: list = []
_base_b_model = None
_stacker_model = None
_calibrator = None
_loaded = False

app = Flask(__name__)


def _resolve(raw_path: str) -> Path:
    """解析 bundle 裡的路徑，對應到 /opt/ml/model/ 下。"""
    p = Path(raw_path)
    # 優先在 MODEL_DIR 下找
    if not p.is_absolute():
        candidate = _MODEL_DIR / p
        if candidate.exists():
            return candidate
    if p.exists():
        return p
    # 只用檔名在 models/ 下找
    by_name = _MODEL_DIR / "models" / p.name
    if by_name.exists():
        return by_name
    raise FileNotFoundError(f"找不到: {raw_path}, 嘗試: {_MODEL_DIR / raw_path}, {by_name}")


def _load_models() -> None:
    """首次請求時載入所有模型。"""
    global _bundle, _base_a_models, _base_e_models, _base_d_models
    global _base_b_model, _stacker_model, _calibrator, _loaded

    # 設定 BITOGUARD_ARTIFACT_DIR 指向 model dir，讓 bundle._remap_path 能解析
    os.environ["BITOGUARD_ARTIFACT_DIR"] = str(_MODEL_DIR)

    _bundle = load_selected_bundle(require_ready=True)

    # Base A: CatBoost ×N seeds
    a_paths = _bundle["base_model_paths"].get("base_a_catboost_seeds") or \
              [_bundle["base_model_paths"]["base_a_catboost"]]
    _base_a_models = [load_pickle(_resolve(p)) for p in a_paths]
    print(f"[serve] Base A: {len(_base_a_models)} CatBoost models")

    # Base B: transductive CatBoost（endpoint 模式下可用，但 transductive features 為 0）
    b_path = _bundle["base_model_paths"].get("base_b_catboost")
    if b_path:
        try:
            _base_b_model = load_pickle(_resolve(b_path))
            print("[serve] Base B: loaded")
        except FileNotFoundError:
            print("[serve] Base B: not found, skipping")

    # Base D: LightGBM ×N seeds
    d_paths = _bundle["base_model_paths"].get("base_d_lgbm_seeds") or \
              [_bundle["base_model_paths"].get("base_d_lgbm")]
    d_paths = [p for p in d_paths if p]
    for p in d_paths:
        try:
            _base_d_models.append(load_pickle(_resolve(p)))
        except FileNotFoundError:
            pass
    print(f"[serve] Base D: {len(_base_d_models)} LightGBM models")

    # Base E: XGBoost ×N seeds
    e_paths = _bundle["base_model_paths"].get("base_e_xgboost_seeds") or \
              [_bundle["base_model_paths"].get("base_e_xgboost")]
    e_paths = [p for p in e_paths if p]
    for p in e_paths:
        try:
            _base_e_models.append(load_pickle(_resolve(p)))
        except FileNotFoundError:
            pass
    print(f"[serve] Base E: {len(_base_e_models)} XGBoost models")

    # Stacker + Calibrator
    _stacker_model = load_pickle(_resolve(_bundle["stacker_path"]))
    _calibrator = load_pickle(_resolve(_bundle["calibrator"]["calibrator_path"]))
    print(f"[serve] Stacker + Calibrator loaded")
    print(f"[serve] Threshold: {_bundle['selected_threshold']}")

    _loaded = True


def _predict(input_df: pd.DataFrame) -> pd.DataFrame:
    """Endpoint 推論流程。"""
    if not _loaded:
        _load_models()

    feature_cols_a = _bundle["feature_columns_base_a"]
    features = input_df[feature_cols_a].fillna(0)

    # Base A: CatBoost 平均
    base_a = np.mean(
        [m.predict_proba(features)[:, 1] for m in _base_a_models], axis=0
    )

    # Base E: XGBoost（需 encode categorical）
    if _base_e_models:
        e_cols = _bundle.get("feature_columns_base_e", feature_cols_a)
        enc_cols = _bundle.get("encoded_columns_base_e")
        x_e, _ = encode_frame(input_df[e_cols].fillna(0), e_cols, reference_columns=enc_cols)
        base_e = np.mean(
            [m.predict_proba(x_e)[:, 1] for m in _base_e_models], axis=0
        )
    else:
        base_e = np.zeros(len(input_df))

    # Base D: LightGBM
    if _base_d_models:
        d_cols = _bundle.get("feature_columns_base_d", feature_cols_a)
        enc_cols_d = _bundle.get("encoded_columns_base_d")
        x_d, _ = encode_frame(input_df[d_cols].fillna(0), d_cols, reference_columns=enc_cols_d)
        base_d = np.mean(
            [m.predict_proba(x_d)[:, 1] for m in _base_d_models], axis=0
        )
    else:
        base_d = np.zeros(len(input_df))

    # Endpoint 退化：C&S = Base A, Base C (graph) = 0, Base B transductive = 0
    scoring = input_df.copy()
    scoring["base_a_probability"] = base_a
    scoring["base_c_s_probability"] = base_a  # C&S 退化
    scoring["base_b_probability"] = 0.0
    scoring["base_c_probability"] = 0.0       # 無 GraphSAGE
    scoring["base_d_probability"] = base_d
    scoring["base_e_probability"] = base_e

    # 21 meta features（用 official stacking 模組的函式）
    scoring = _add_base_meta_features(scoring)

    available_cols = [c for c in STACKER_FEATURE_COLUMNS if c in scoring.columns]
    stacker_prob = _stacker_model.predict_proba(scoring[available_cols])[:, 1]
    calibrated = _calibrator.predict(stacker_prob)
    threshold = float(_bundle["selected_threshold"])
    status = (calibrated >= threshold).astype(int)

    return pd.DataFrame({
        "user_id": input_df["user_id"].values if "user_id" in input_df.columns else range(len(input_df)),
        "probability": calibrated,
        "status": status,
    })


@app.route("/ping", methods=["GET"])
def ping():
    try:
        if not _loaded:
            _load_models()
        return Response(status=200, response="ok")
    except Exception:
        traceback.print_exc()
        return Response(status=503, response="model load failed")


@app.route("/invocations", methods=["POST"])
def invocations():
    try:
        content_type = request.content_type or "application/json"
        if "json" in content_type:
            payload = request.get_json(force=True)
            if "instances" in payload:
                input_df = pd.DataFrame(payload["instances"])
            elif "data" in payload:
                input_df = pd.DataFrame(payload["data"])
            else:
                input_df = pd.DataFrame([payload])
        elif "csv" in content_type:
            input_df = pd.read_csv(io.StringIO(request.data.decode("utf-8")))
        else:
            return Response(status=415, response=json.dumps({"error": f"Unsupported: {content_type}"}),
                            mimetype="application/json")

        result = _predict(input_df)
        return Response(
            status=200,
            response=json.dumps({
                "predictions": result.to_dict(orient="records"),
                "threshold": float(_bundle["selected_threshold"]),
            }, ensure_ascii=False),
            mimetype="application/json",
        )
    except Exception as e:
        traceback.print_exc()
        return Response(status=500, response=json.dumps({"error": str(e)}), mimetype="application/json")


if __name__ == "__main__":
    _load_models()
    app.run(host="0.0.0.0", port=8080)
