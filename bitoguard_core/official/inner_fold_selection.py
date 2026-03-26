"""Inner-fold selection: blend weights, stacker, calibration, threshold.

All selection is fitted on train_fold only, then applied to valid_fold.
This eliminates in-sample selection bias from the reported OOF metrics.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from official.stacking import (
    STACKER_FEATURE_COLUMNS,
    BlendEnsemble,
    _add_base_meta_features,
    tune_blend_weights,
)
from official.thresholding import search_threshold


def select_and_apply_inner_fold(
    train_oof: pd.DataFrame,
    valid_oof: pd.DataFrame,
    fold_column: str,
    stacker_feature_columns: list[str],
    calibration_method: str = "isotonic",
    n_bootstrap: int = 50,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Given train/valid OOF base model predictions for one outer fold:
    1. tune_blend_weights() on train_oof only
    2. Build BlendEnsemble stacker (no inner folds needed)
    3. Apply selected stacker to valid_oof → stacker_raw_probability
    4. choose_best_calibration_and_threshold() on train_oof only
    5. Apply calibrator + threshold to valid_oof → submission_probability

    Returns valid_oof with submission_probability column, plus metadata dict.
    """
    # Add meta features to both train and valid
    train_oof = _add_base_meta_features(train_oof.copy())
    valid_oof = _add_base_meta_features(valid_oof.copy())

    # 1. Tune blend weights on train only
    blend_weights = tune_blend_weights(train_oof)
    blend_model = BlendEnsemble(blend_weights)

    # 2. Apply blend model to both train and valid
    available_cols = [c for c in stacker_feature_columns if c in train_oof.columns]
    train_oof["stacker_raw_probability"] = blend_model.predict_proba(train_oof[available_cols])[:, 1]
    valid_oof["stacker_raw_probability"] = blend_model.predict_proba(valid_oof[available_cols])[:, 1]

    # 3. Choose calibration and threshold on train only
    train_labels = train_oof["status"].astype(int).to_numpy()
    train_raw_probs = train_oof["stacker_raw_probability"].to_numpy()
    train_groups = train_oof.get("primary_fold", pd.Series(0, index=train_oof.index)).to_numpy()

    # Simple calibration: isotonic or identity
    if calibration_method == "isotonic":
        from official.calibration import IsotonicCalibrator
        calibrator = IsotonicCalibrator().fit(train_raw_probs, train_labels)
    else:
        from official.stacking import IdentityCalibrator
        calibrator = IdentityCalibrator()

    train_calibrated = calibrator.predict(train_raw_probs)

    # 4. Search threshold on train only
    threshold_report = search_threshold(
        train_labels,
        train_calibrated,
        train_groups,
        beta=1.0,
        n_bootstrap=n_bootstrap,
    )
    selected_threshold = float(threshold_report["selected_threshold"])

    # 5. Apply calibrator and threshold to valid
    valid_raw_probs = valid_oof["stacker_raw_probability"].to_numpy()
    valid_calibrated = calibrator.predict(valid_raw_probs)
    valid_oof["submission_probability"] = valid_calibrated

    metadata = {
        "blend_weights": blend_weights,
        "calibration_method": calibration_method,
        "selected_threshold": selected_threshold,
        "threshold_report": threshold_report,
    }

    return valid_oof, metadata


def honest_oof_evaluation(
    oof_frame: pd.DataFrame,
    fold_column: str = "primary_fold",
    stacker_feature_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Run inner-fold selection across all folds for honest OOF metrics.

    For each outer fold k:
      - train = folds != k
      - valid = fold == k
      - Fit blend weights + calibration + threshold on train only
      - Apply to valid → honest predictions

    Args:
        oof_frame: Full OOF DataFrame with base model probabilities,
                   'status' column, and fold assignments.
        fold_column: Column name containing fold IDs.
        stacker_feature_columns: Columns to use. Defaults to STACKER_FEATURE_COLUMNS.

    Returns:
        Tuple of (concatenated honest OOF predictions, list of per-fold metadata).
    """
    if stacker_feature_columns is None:
        stacker_feature_columns = list(STACKER_FEATURE_COLUMNS)

    fold_ids = sorted(int(v) for v in oof_frame[fold_column].dropna().unique())
    honest_parts: list[pd.DataFrame] = []
    fold_metas: list[dict[str, Any]] = []

    for fold_id in fold_ids:
        train_mask = oof_frame[fold_column] != fold_id
        valid_mask = oof_frame[fold_column] == fold_id

        train_oof = oof_frame[train_mask].copy()
        valid_oof = oof_frame[valid_mask].copy()

        valid_result, fold_meta = select_and_apply_inner_fold(
            train_oof, valid_oof,
            fold_column=fold_column,
            stacker_feature_columns=stacker_feature_columns,
        )
        fold_meta["fold_id"] = fold_id
        fold_meta["train_size"] = int(train_mask.sum())
        fold_meta["valid_size"] = int(valid_mask.sum())
        honest_parts.append(valid_result)
        fold_metas.append(fold_meta)

        print(
            f"  [honest fold {fold_id}] "
            f"train={fold_meta['train_size']:,} valid={fold_meta['valid_size']:,} "
            f"method={fold_meta['calibration_method']} "
            f"threshold={fold_meta['selected_threshold']:.4f}"
        )

    honest_oof = (
        pd.concat(honest_parts, ignore_index=True)
        .sort_values("user_id")
        .reset_index(drop=True)
    )
    return honest_oof, fold_metas

