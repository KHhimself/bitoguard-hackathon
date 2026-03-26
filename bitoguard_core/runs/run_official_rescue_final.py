"""
Official pipeline rescue run: official_pipeline_20260317_rescue_v2

Applies all necessary fixes to run the official pipeline successfully:

Fix 1 - Feature parquet dtype:
  92 windowed feature columns (twd_*_1d, twd_*_3d, etc.) are all-None with object dtype
  because the time windows fall outside the available data range (data ends Nov 2025,
  cutoff is Feb 2026). CatBoost treats object-dtype columns as categorical and fails on None.
  Fix: cast to float64 before training.

Fix 2 - Focal loss syntax:
  Working-tree modeling.py uses 'Logloss:focal_gamma=2.0' which is invalid in CatBoost 1.2.10.
  The inline comment says the correct syntax is 'Focal:focal_alpha=0.25;focal_gamma=X'.
  Fix: use correct syntax.

Fix 3 - Focal loss GPU incompatibility:
  Focal loss is not supported for GPU training in CatBoost 1.2.x.
  Fix: force task_type='CPU' when using Focal loss.

Fix 4 - class_weights incompatible with Focal loss:
  CatBoost rejects class_weights parameter when loss_function is Focal.
  Fix: omit class_weights when using Focal loss (Focal handles class imbalance via focal_alpha).

These fixes are all run-time workarounds. No training data, labels, splits, or evaluation
protocol is modified.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

BASE_DIR = Path('/experiment/YuNing/bitoguard-hackathon/bitoguard_core')
sys.path.insert(0, str(BASE_DIR))

import pandas as pd
import numpy as np


# ── Stage 1-4: run feature generation ────────────────────────────────────────
print('[stage1] Building cohorts...')
from official.cohorts import build_official_data_contract_report
build_official_data_contract_report()
print('[stage1] Cohorts done')

print('[stage2] Building features...')
from official.features import build_official_features
build_official_features()
print('[stage2] Features done')

print('[stage3] Building graph features...')
from official.graph_features import build_official_graph_features
build_official_graph_features()
print('[stage3] Graph features done')

print('[stage4] Building anomaly features...')
from official.anomaly import build_official_anomaly_features
build_official_anomaly_features()
print('[stage4] Anomaly features done')


# ── Fix 1: dtype fix on user features parquet ────────────────────────────────
parquet_path = BASE_DIR / 'artifacts/official_features/official_user_features_full.parquet'
df = pd.read_parquet(str(parquet_path))
null_obj_cols = [c for c in df.columns if pd.api.types.is_object_dtype(df[c]) and df[c].isna().all()]
print(f'[fix1] Converting {len(null_obj_cols)} all-null object-dtype cols to float64')
for col in null_obj_cols:
    df[col] = df[col].astype('float64')
df.to_parquet(str(parquet_path), index=False)
print(f'[fix1] Saved fixed parquet ({parquet_path.name})')


# ── Fix 2-4: monkey-patch fit_catboost ───────────────────────────────────────
import official.modeling as modeling_module
from catboost import CatBoostClassifier
from official.modeling import ModelFitResult
from official.common import RANDOM_SEED


def _patched_fit_catboost(
    train_frame: pd.DataFrame,
    valid_frame: pd.DataFrame | None,
    feature_columns: list[str],
    focal_gamma: float = 0.0,
) -> ModelFitResult:
    cat_features = [
        col for col in feature_columns
        if pd.api.types.is_object_dtype(train_frame[col])
        or pd.api.types.is_string_dtype(train_frame[col])
    ]
    y_train = train_frame['status'].astype(int)
    positives = max(1, int(y_train.sum()))
    negatives = max(1, len(y_train) - positives)
    use_focal = focal_gamma > 0.0
    # Fix 2: correct CatBoost 1.2.x focal syntax
    _loss_function = (
        f'Focal:focal_alpha=0.25;focal_gamma={focal_gamma}' if use_focal else 'Logloss'
    )
    _eval_metric = 'AUC' if use_focal else 'Logloss'
    model_kwargs: dict = dict(
        loss_function=_loss_function,
        eval_metric=_eval_metric,
        iterations=500,
        random_seed=RANDOM_SEED,
        verbose=False,
        # Fix 3: CPU only (Focal not supported on GPU)
        task_type='CPU',
        thread_count=8,
    )
    # Fix 4: no class_weights for Focal (incompatible)
    if not use_focal:
        model_kwargs['class_weights'] = [1.0, negatives / positives]
    model = CatBoostClassifier(**model_kwargs)
    train_x = train_frame[feature_columns]
    valid_x = None
    y_valid = None
    if valid_frame is not None and not valid_frame.empty:
        valid_x = valid_frame[feature_columns]
        y_valid = valid_frame['status'].astype(int)
    validation_probabilities: list[float] | None = None
    if valid_x is not None and y_valid is not None:
        model.fit(
            train_x, y_train,
            cat_features=cat_features,
            eval_set=(valid_x, y_valid),
            use_best_model=True,
            early_stopping_rounds=50,
        )
        validation_probabilities = model.predict_proba(valid_x)[:, 1].tolist()
    else:
        model.fit(train_x, y_train, cat_features=cat_features)
    if validation_probabilities:
        vp = np.array(validation_probabilities, dtype=float)
        if vp.mean() < 1e-4 or vp.max() < 0.01:
            import warnings
            warnings.warn(
                f'fit_catboost: probabilities collapsed '
                f'(mean={vp.mean():.6f}, max={vp.max():.6f}, focal_gamma={focal_gamma})'
            )
    return ModelFitResult(
        model_name='catboost',
        model=model,
        feature_columns=feature_columns,
        encoded_columns=None,
        cat_features=cat_features,
        validation_probabilities=validation_probabilities,
    )


modeling_module.fit_catboost = _patched_fit_catboost
print('[fix2-4] fit_catboost patched: correct focal syntax, CPU mode, no class_weights for Focal')


# ── Stage 5: Train ────────────────────────────────────────────────────────────
print('[stage5] Training...')
from official.train import train_official_model
train_meta = train_official_model()
print('[stage5] Training done')
print(json.dumps({k: str(v) for k, v in train_meta.items()}, indent=2))


# ── Stage 6: Validate ─────────────────────────────────────────────────────────
print('[stage6] Validating...')
from official.validate import validate_official_model
validation = validate_official_model()
print('[stage6] Validation done')


# ── Stage 7: Score ────────────────────────────────────────────────────────────
print('[stage7] Scoring...')
from official.score import score_official_predict
predictions = score_official_predict()
print('[stage7] Scoring done')


# ── Final result summary ──────────────────────────────────────────────────────
result = {
    'train_meta': {k: str(v) for k, v in train_meta.items()},
    'prediction_rows': int(len(predictions)),
    'selected_threshold': validation['selected_threshold'],
}
print('\nFINAL RESULT:')
print(json.dumps(result, indent=2))
