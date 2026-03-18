from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from official.calibration import BetaCalibrator, IsotonicCalibrator, SigmoidCalibrator
from official.common import RANDOM_SEED, load_official_paths, save_pickle
from official.thresholding import search_threshold
from models.pu_learning import estimate_c, pu_adjust


class IdentityCalibrator:
    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> "IdentityCalibrator":
        return self

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        return np.asarray(probabilities, dtype=float)


# Base model probabilities + anomaly/rule meta-features fed to the stacker.
# v30: Simplified to core 9 features — removed lof/ocsvm (weak, AP<0.09) and
# individual rule flags (rule_score already captures combined effect). Keeping
# max/std meta-features for model-consensus signal.
STACKER_FEATURE_COLUMNS = [
    "base_a_probability",
    "base_b_probability",
    "base_c_probability",
    "base_d_probability",
    "base_e_probability",
    "rule_score",
    "anomaly_score",
    # Meta-features computed from base probabilities.
    # max_base: at least one model strongly suspects fraud.
    # std_base: model disagreement — high std suggests uncertain/novel case.
    "max_base_probability",
    "std_base_probability",
]

_BASE_PROB_COLUMNS = [
    "base_a_probability", "base_b_probability", "base_c_probability",
    "base_d_probability", "base_e_probability",
]


def _add_base_meta_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute max/std across base model probabilities for stacker enrichment."""
    frame = frame.copy()
    available = [c for c in _BASE_PROB_COLUMNS if c in frame.columns]
    if available:
        frame["max_base_probability"] = frame[available].max(axis=1)
        frame["std_base_probability"] = frame[available].std(axis=1).fillna(0.0)
    else:
        frame["max_base_probability"] = 0.0
        frame["std_base_probability"] = 0.0
    return frame


CALIBRATION_CANDIDATES = {
    "raw": IdentityCalibrator,
    "sigmoid": SigmoidCalibrator,
    "beta": BetaCalibrator,
    "isotonic": IsotonicCalibrator,
}


def fit_logistic_stacker(frame: pd.DataFrame, feature_columns: list[str]) -> LogisticRegression:
    model = LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)
    model.fit(frame[feature_columns], frame["status"].astype(int))
    return model


def _fit_catboost_stacker(frame: pd.DataFrame, feature_columns: list[str]) -> Any:
    """Fit a shallow CatBoost stacker for non-linear meta-learning.

    Depth=3 is intentionally shallow to avoid overfitting on the ~50k OOF
    meta-features. Heavy L2 regularization + min_data_in_leaf=30 ensure
    the model only splits on genuinely useful non-linear interactions.
    """
    try:
        from catboost import CatBoostClassifier
    except ImportError:
        return fit_logistic_stacker(frame, feature_columns)

    y = frame["status"].astype(int)
    positives = max(1, int(y.sum()))
    negatives = max(1, len(y) - positives)
    # Cap positive class weight at 5x for the stacker (meta-features are already
    # calibrated probabilities, so extreme imbalance handling is less needed).
    class_weight_ratio = min(float(negatives) / positives, 5.0)
    cat_features = [c for c in feature_columns if frame[c].dtype == bool or str(frame[c].dtype) == "bool"]

    model = CatBoostClassifier(
        depth=3,
        iterations=400,
        learning_rate=0.05,
        l2_leaf_reg=15.0,
        min_data_in_leaf=30,
        random_strength=0.5,
        class_weights=[1.0, class_weight_ratio],
        loss_function="Logloss",
        eval_metric="Logloss",
        random_seed=RANDOM_SEED,
        verbose=False,
    )
    x = frame[feature_columns].copy()
    for c in feature_columns:
        if x[c].dtype == bool or str(x[c].dtype) == "bool":
            x[c] = x[c].astype(int)
    model.fit(x, y)
    return model


def _predict_stacker(model: Any, frame: pd.DataFrame, feature_columns: list[str]) -> np.ndarray:
    """Unified predict that works for both LR and CatBoost stackers."""
    x = frame[feature_columns].copy()
    for c in feature_columns:
        if x[c].dtype == bool or str(x[c].dtype) == "bool":
            x[c] = x[c].astype(int)
    return model.predict_proba(x)[:, 1]


def build_stacker_oof(
    base_oof_frame: pd.DataFrame,
    split_frame: pd.DataFrame,
    fold_column: str = "primary_fold",
    use_nonlinear: bool = False,
) -> tuple[pd.DataFrame, Any]:
    if fold_column in base_oof_frame.columns:
        frame = base_oof_frame.copy()
    else:
        frame = base_oof_frame.merge(split_frame[["user_id", fold_column]], on="user_id", how="left")
    if frame[fold_column].isna().any():
        raise ValueError(f"Missing fold assignments in {fold_column}")

    # Enrich with base-probability meta-features (max, std across models).
    frame = _add_base_meta_features(frame)

    # Only use features that are actually present in the frame.
    available_cols = [c for c in STACKER_FEATURE_COLUMNS if c in frame.columns]

    oof_rows: list[pd.DataFrame] = []
    for fold_id in sorted(int(value) for value in frame[fold_column].dropna().unique()):
        valid_frame = frame[frame[fold_column] == fold_id].copy()
        train_frame = frame[frame[fold_column] != fold_id].copy()
        if use_nonlinear:
            model = _fit_catboost_stacker(train_frame, available_cols)
        else:
            model = fit_logistic_stacker(train_frame, available_cols)
        valid_frame["stacker_raw_probability"] = _predict_stacker(model, valid_frame, available_cols)
        oof_rows.append(valid_frame)
    oof_frame = pd.concat(oof_rows, ignore_index=True).sort_values("user_id").reset_index(drop=True)
    if use_nonlinear:
        final_model = _fit_catboost_stacker(frame, available_cols)
    else:
        final_model = fit_logistic_stacker(frame, available_cols)
    return oof_frame, final_model


def choose_best_calibration_and_threshold(
    raw_probabilities: np.ndarray,
    labels: np.ndarray,
    group_ids: np.ndarray | None,
    use_pu_adjustment: bool = True,
) -> tuple[dict[str, Any], Any, np.ndarray]:
    labels = np.asarray(labels, dtype=int)
    raw_probabilities = np.asarray(raw_probabilities, dtype=float)
    paths = load_official_paths()
    candidate_rows: list[dict[str, Any]] = []
    best_rank: tuple[float, float, float] | None = None
    best_payload: tuple[dict[str, Any], Any, np.ndarray] | None = None

    for method, builder in CALIBRATION_CANDIDATES.items():
        calibrator = builder().fit(raw_probabilities, labels)
        calibrated = calibrator.predict(raw_probabilities)

        # PU Learning adjustment (Elkan-Noto 2008): rescale calibrated
        # probabilities to account for unlabeled true positives.
        if use_pu_adjustment:
            c_estimate = estimate_c(calibrated, labels)
            pu_calibrated = pu_adjust(calibrated, c_estimate)
        else:
            c_estimate = None
            pu_calibrated = calibrated

        threshold_report = search_threshold(labels, pu_calibrated, group_ids, beta=1.0)
        selected_row = threshold_report["selected_row"]
        ap = float(average_precision_score(labels, pu_calibrated))
        candidate_report = {
            "method": method,
            "average_precision": ap,
            "selected_threshold": float(threshold_report["selected_threshold"]),
            "selected_row": dict(selected_row),
            "threshold_report": threshold_report,
            "pu_c_estimate": float(c_estimate) if c_estimate is not None else None,
        }
        candidate_rows.append(candidate_report)
        rank = (
            float(selected_row["bootstrap_mean_f1"]),
            ap,
            -float(selected_row["fpr"]),
        )
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_payload = (candidate_report, calibrator, pu_calibrated, c_estimate)

    assert best_payload is not None
    selected_report, calibrator, pu_calibrated, c_estimate = best_payload
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calibrator_path = paths.model_dir / f"official_stacker_calibrator_{selected_report['method']}_{timestamp}.pkl"
    save_pickle(calibrator, calibrator_path)
    report = {
        "method": selected_report["method"],
        "average_precision": selected_report["average_precision"],
        "selected_threshold": selected_report["selected_threshold"],
        "selected_row": selected_report["selected_row"],
        "threshold_report": selected_report["threshold_report"],
        "calibrator_path": str(calibrator_path),
        "candidates": candidate_rows,
        "selection_basis": {
            "priority": ["best_bootstrap_mean_f1", "best_average_precision", "lowest_fpr"],
        },
        "pu_c_estimate": float(c_estimate) if c_estimate is not None else None,
        "pu_adjustment_enabled": use_pu_adjustment,
    }
    return report, calibrator, pu_calibrated


def save_stacker_model(model: Any, path: Path) -> None:
    save_pickle(model, path)
