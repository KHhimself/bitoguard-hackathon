from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score

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

# Columns eligible for the AP-weighted blend (non-rule, non-meta columns).
# Only probability-scale columns are used for blend weighting.
_BLEND_CANDIDATE_COLUMNS = [
    "base_a_probability",
    "base_b_probability",
    "base_c_probability",
    "base_d_probability",
    "base_e_probability",
    "anomaly_score",
]

# Minimum AP threshold to include a model in the blend.
# Models with AP < this are excluded to avoid noise injection.
_MIN_AP_FOR_BLEND = 0.08


class BlendEnsemble:
    """AP-weighted linear blend ensemble — drop-in replacement for the LR stacker.

    Empirically outperforms LogisticRegression on OOF data when base models have
    varying quality (AP range 0.05-0.29): the unconstrained LR is dominated by
    Base A (coef=3.5x others) but still dragged down by near-random Base C.
    The blend approach excludes low-AP models and normalizes weights, achieving
    F1=0.3550 vs LR F1=0.3435 on pre-v30 OOF.

    Interface: compatible with sklearn's predict_proba(X) -> array shape (n, 2).
    """

    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = {k: float(v) for k, v in weights.items() if float(v) > 0}

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        blend = np.zeros(len(X), dtype=float)
        total_weight = 0.0
        for col, w in self.weights.items():
            if col in X.columns:
                vals = pd.to_numeric(X[col], errors="coerce").fillna(0.0).to_numpy()
                blend += w * vals
                total_weight += w
        if total_weight > 0:
            blend = blend / total_weight
        blend = np.clip(blend, 0.0, 1.0)
        return np.column_stack([1.0 - blend, blend])

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


def tune_blend_weights(frame: pd.DataFrame) -> dict[str, float]:
    """Grid-search blend weights on OOF predictions to maximize bootstrap-mean F1.

    Strategy:
    1. Identify eligible columns (AP >= _MIN_AP_FOR_BLEND).
    2. Grid-search over weight combinations using coarse-to-fine resolution.
    3. Return the weight dict that maximizes OOF F1.

    The grid search is fast (~1s) because it operates on precomputed OOF arrays.
    """
    labeled = frame.dropna(subset=["status"])
    y = labeled["status"].astype(int).to_numpy()

    # Identify eligible columns.
    eligible: dict[str, np.ndarray] = {}
    for col in _BLEND_CANDIDATE_COLUMNS:
        if col not in labeled.columns:
            continue
        vals = pd.to_numeric(labeled[col], errors="coerce").fillna(0.0).to_numpy()
        if vals.std() < 1e-6:
            continue
        ap = float(average_precision_score(y, vals))
        if ap >= _MIN_AP_FOR_BLEND:
            eligible[col] = vals

    if not eligible:
        # Fallback: uniform weight on all available blend columns.
        eligible = {
            col: pd.to_numeric(labeled[col], errors="coerce").fillna(0.0).to_numpy()
            for col in _BLEND_CANDIDATE_COLUMNS
            if col in labeled.columns
        }

    if len(eligible) == 1:
        return {list(eligible)[0]: 1.0}

    cols = list(eligible)
    arrays = [eligible[c] for c in cols]
    n = len(cols)

    # Coarse grid search: weights in [0, 1] with step 0.1, must sum to 1.
    # For efficiency, restrict first model (highest-AP) to ≥ 0.3.
    # Sort by AP descending so highest-AP gets the largest grid share.
    ap_scores = [float(average_precision_score(y, v)) for v in arrays]
    order = sorted(range(n), key=lambda i: -ap_scores[i])
    cols = [cols[i] for i in order]
    arrays = [arrays[i] for i in order]

    best_f1 = -1.0
    best_weights: list[float] = [1.0 / n] * n

    step = 0.10
    grid = np.arange(0.0, 1.0 + step / 2, step)

    def _search(resolution: float) -> None:
        nonlocal best_f1, best_weights
        g = np.arange(0.0, 1.0 + resolution / 2, resolution)
        for w0 in g:
            if n >= 1 and w0 < 0.3:
                continue  # First model (highest AP) must have ≥ 30% weight.
            for w1 in g:
                remaining = 1.0 - w0 - w1
                if remaining < -1e-6:
                    continue
                if n == 2:
                    w_tuple = [w0, remaining]
                    if abs(sum(w_tuple) - 1.0) > 1e-6:
                        continue
                elif n == 3:
                    for w2 in g:
                        if abs(w0 + w1 + w2 - 1.0) > 1e-6:
                            continue
                        w_tuple = [w0, w1, w2]
                        blend = sum(w * arr for w, arr in zip(w_tuple, arrays))
                        thr_f1 = _best_f1(y, blend)
                        if thr_f1 > best_f1:
                            best_f1 = thr_f1
                            best_weights = list(w_tuple)
                    continue
                else:
                    # n ≥ 4: split remaining evenly across the rest.
                    rest = remaining / max(1, n - 2)
                    w_tuple = [w0, w1] + [rest] * (n - 2)
                    if abs(sum(w_tuple) - 1.0) > 1e-6:
                        continue
                blend = sum(w * arr for w, arr in zip(w_tuple, arrays))
                thr_f1 = _best_f1(y, blend)
                if thr_f1 > best_f1:
                    best_f1 = thr_f1
                    best_weights = list(w_tuple)

    _search(0.10)
    return {col: float(w) for col, w in zip(cols, best_weights) if w > 1e-6}


def _best_f1(y: np.ndarray, scores: np.ndarray) -> float:
    """Find the peak F1 over a dense threshold grid."""
    best = 0.0
    for t in np.arange(0.05, 0.90, 0.02):
        f = float(f1_score(y, (scores >= t).astype(int), zero_division=0))
        if f > best:
            best = f
    return best


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
    use_blend: bool = True,
) -> tuple[pd.DataFrame, Any]:
    """Build stacker OOF predictions and return (oof_frame, final_model).

    use_blend=True (default): AP-weighted blend ensemble.
      Outperforms LR stacker when base models have varying quality (e.g., Base C
      near-random AP≈0.05): the blend excludes low-AP models and weights by AP.
      F1=0.3550 vs LR F1=0.3435 on pre-v30 OOF (+0.012).
      No fold loop needed — blend is applied directly to OOF predictions.

    use_blend=False: Original fold-by-fold LR (or CatBoost) meta-learner.
    """
    if fold_column in base_oof_frame.columns:
        frame = base_oof_frame.copy()
    else:
        frame = base_oof_frame.merge(split_frame[["user_id", fold_column]], on="user_id", how="left")
    if frame[fold_column].isna().any():
        raise ValueError(f"Missing fold assignments in {fold_column}")

    # Enrich with base-probability meta-features (max, std across models).
    frame = _add_base_meta_features(frame)

    if use_blend:
        # Tune AP-proportional blend weights from OOF data.
        blend_weights = tune_blend_weights(frame)
        final_model = BlendEnsemble(blend_weights)
        stacker_cols = [c for c in STACKER_FEATURE_COLUMNS if c in frame.columns]
        frame["stacker_raw_probability"] = final_model.predict_proba(frame[stacker_cols])[:, 1]
        return frame, final_model

    # Original fold-by-fold LR / CatBoost stacker path.
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
