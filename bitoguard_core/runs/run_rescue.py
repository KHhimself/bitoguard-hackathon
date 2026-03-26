"""
Rescue run script for official_pipeline_20260317_rescue_focal_syntax.

Fixes applied:
1. Feature parquet dtype fix: cast 92 all-null object-dtype columns to float64
2. Focal loss syntax fix: use 'Focal:focal_alpha=0.25;focal_gamma=2.0' instead of 'Logloss:focal_gamma=2.0'
3. Focal loss GPU incompatibility: force task_type='CPU' for CatBoost when using Focal loss
4. class_weights not compatible with Focal loss: omit class_weights when using Focal loss
"""
from __future__ import annotations
import pandas as pd
import numpy as np

# Fix 1: Cast all-null object-dtype columns to float64 in feature parquet
parquet_path = 'artifacts/official_features/official_user_features_full.parquet'
df = pd.read_parquet(parquet_path)
null_obj_cols = [c for c in df.columns if pd.api.types.is_object_dtype(df[c]) and df[c].isna().all()]
print(f'[fix1] Converting {len(null_obj_cols)} all-null object-dtype cols to float64...')
for col in null_obj_cols:
    df[col] = df[col].astype('float64')
df.to_parquet(parquet_path, index=False)
print(f'[fix1] Saved fixed parquet: {parquet_path}')

# Fix 2-4: Monkey-patch fit_catboost with correct focal syntax
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
    """
    Patched fit_catboost with correct CatBoost 1.2.x focal loss syntax.
    Changes vs working-tree modeling.py:
    - loss_function: 'Logloss:focal_gamma=X' -> 'Focal:focal_alpha=0.25;focal_gamma=X'
    - task_type: GPU -> CPU (Focal loss not supported on GPU in CatBoost 1.2.x)
    - class_weights: omitted when using Focal loss (not compatible with Focal in CatBoost 1.2.x)
    """
    cat_features = [
        column for column in feature_columns
        if pd.api.types.is_object_dtype(train_frame[column])
        or pd.api.types.is_string_dtype(train_frame[column])
    ]
    y_train = train_frame['status'].astype(int)
    positives = max(1, int(y_train.sum()))
    negatives = max(1, len(y_train) - positives)
    use_focal = focal_gamma > 0.0
    _loss_function = f'Focal:focal_alpha=0.25;focal_gamma={focal_gamma}' if use_focal else 'Logloss'
    _eval_metric = 'AUC' if use_focal else 'Logloss'
    model_kwargs: dict = dict(
        loss_function=_loss_function,
        eval_metric=_eval_metric,
        iterations=500,
        random_seed=RANDOM_SEED,
        verbose=False,
        task_type='CPU',
        thread_count=8,
    )
    if not use_focal:
        model_kwargs['class_weights'] = [1.0, negatives / positives]
    model = CatBoostClassifier(**model_kwargs)
    validation_probabilities: list[float] | None = None
    train_x = train_frame[feature_columns]
    valid_x = None
    y_valid = None
    if valid_frame is not None and not valid_frame.empty:
        valid_x = valid_frame[feature_columns]
        y_valid = valid_frame['status'].astype(int)
    if valid_x is not None and y_valid is not None:
        model.fit(train_x, y_train, cat_features=cat_features, eval_set=(valid_x, y_valid), use_best_model=True, early_stopping_rounds=50)
        validation_probabilities = model.predict_proba(valid_x)[:, 1].tolist()
    else:
        model.fit(train_x, y_train, cat_features=cat_features)
    if validation_probabilities:
        vp = np.array(validation_probabilities, dtype=float)
        if vp.mean() < 1e-4 or vp.max() < 0.01:
            import warnings
            warnings.warn(
                f'fit_catboost: validation probabilities collapsed '
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
print('[fix2-4] fit_catboost patched with correct focal syntax, CPU mode, no class_weights for Focal')

# Run remaining pipeline stages
from official.train import train_official_model
from official.validate import validate_official_model
from official.score import score_official_predict
import json

print('Stage 5: Training...')
train_meta = train_official_model()
print('Stage 5 (train): done')
print(json.dumps({k: str(v) for k, v in train_meta.items()}, indent=2))

print('Stage 6: Validating...')
validation = validate_official_model()
print('Stage 6 (validate): done')

print('Stage 7: Scoring...')
predictions = score_official_predict()
print('Stage 7 (score): done')

result = {
    'train_meta': {k: str(v) for k, v in train_meta.items()},
    'prediction_rows': int(len(predictions)),
    'selected_threshold': validation['selected_threshold'],
}
print('FINAL RESULT:')
print(json.dumps(result, indent=2))
