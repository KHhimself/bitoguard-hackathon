"""Optuna hyperparameter optimization for CatBoost Base A.

Usage:
    cd bitoguard_core && source .venv/bin/activate
    PYTHONPATH=. python -m official.hpo --n-trials 30

This module runs an Optuna study that tunes CatBoost Base A hyperparameters
using the same 5-fold StratifiedKFold split as the primary validation.
The objective is OOF F1 score (computed via the stacker pipeline).

The best parameters are saved to artifacts/official_features/hpo_best_params.json
and can be loaded by train.py to replace default CatBoost parameters.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score

from hardware import catboost_runtime_params
from official.common import RANDOM_SEED, encode_frame, feature_output_path, load_official_paths, save_json
from official.train import (
    LABEL_FREE_EXCLUDED_COLUMNS,
    _load_dataset,
    _label_frame,
    _label_free_feature_columns,
)
from official.transductive_validation import (
    PrimarySplitSpec,
    build_primary_transductive_splits,
    iter_fold_assignments,
)

logger = logging.getLogger(__name__)

# Stacker features for the HPO objective (simplified — no Base B/C/D during HPO
# to keep each trial fast; we only optimize Base A + anomaly + rules).
_HPO_STACKER_COLUMNS = [
    "base_a_probability",
    "rule_score",
    "anomaly_score",
]


def _fit_catboost_trial(
    train_frame: pd.DataFrame,
    valid_frame: pd.DataFrame,
    feature_columns: list[str],
    params: dict[str, Any],
) -> tuple[list[float], Any]:
    """Train CatBoost with trial-specific params and return validation probabilities."""
    from catboost import CatBoostClassifier

    cat_features = [
        col for col in feature_columns
        if pd.api.types.is_object_dtype(train_frame[col])
        or pd.api.types.is_string_dtype(train_frame[col])
        or pd.api.types.is_categorical_dtype(train_frame[col])
    ]
    y_train = train_frame["status"].astype(int)
    y_valid = valid_frame["status"].astype(int)

    positives = max(1, int(y_train.sum()))
    negatives = max(1, len(y_train) - positives)
    weight_ratio = min(float(negatives) / positives, params.get("max_class_weight", 10.0))
    class_weights = [1.0, weight_ratio]

    runtime_params = catboost_runtime_params()

    model = CatBoostClassifier(
        loss_function="Logloss",
        eval_metric="Logloss",
        class_weights=class_weights,
        random_seed=params.get("random_seed", RANDOM_SEED),
        verbose=False,
        iterations=params.get("iterations", 1000),
        depth=params["depth"],
        learning_rate=params["learning_rate"],
        l2_leaf_reg=params.get("l2_leaf_reg", 3.0),
        random_strength=params.get("random_strength", 1.0),
        bagging_temperature=params.get("bagging_temperature", 1.0),
        border_count=params.get("border_count", 254),
        min_data_in_leaf=params.get("min_data_in_leaf", 1),
        **runtime_params,
    )

    try:
        model.fit(
            train_frame[feature_columns], y_train,
            cat_features=cat_features,
            eval_set=(valid_frame[feature_columns], y_valid),
            use_best_model=True,
            early_stopping_rounds=params.get("early_stopping_rounds", 100),
        )
    except Exception:
        # GPU fallback to CPU
        if runtime_params.get("task_type") != "GPU":
            raise
        from hardware import hardware_profile
        model = CatBoostClassifier(
            loss_function="Logloss",
            eval_metric="Logloss",
            class_weights=class_weights,
            random_seed=params.get("random_seed", RANDOM_SEED),
            verbose=False,
            iterations=params.get("iterations", 1000),
            depth=params["depth"],
            learning_rate=params["learning_rate"],
            l2_leaf_reg=params.get("l2_leaf_reg", 3.0),
            random_strength=params.get("random_strength", 1.0),
            bagging_temperature=params.get("bagging_temperature", 1.0),
            border_count=params.get("border_count", 254),
            min_data_in_leaf=params.get("min_data_in_leaf", 1),
            task_type="CPU",
            thread_count=hardware_profile().cpu_threads,
        )
        model.fit(
            train_frame[feature_columns], y_train,
            cat_features=cat_features,
            eval_set=(valid_frame[feature_columns], y_valid),
            use_best_model=True,
            early_stopping_rounds=params.get("early_stopping_rounds", 100),
        )

    val_probs = model.predict_proba(valid_frame[feature_columns])[:, 1].tolist()
    return val_probs, model


def _compute_oof_f1(
    oof_frame: pd.DataFrame,
    stacker_columns: list[str],
    threshold_grid: np.ndarray | None = None,
) -> tuple[float, float]:
    """Compute the best OOF F1 from stacker + threshold search."""
    labels = oof_frame["status"].astype(int).to_numpy()

    # Fit stacker across folds (leave-one-fold-out)
    fold_col = "primary_fold"
    stacker_probs = np.zeros(len(oof_frame))
    for fold_id in sorted(oof_frame[fold_col].unique()):
        train_mask = oof_frame[fold_col] != fold_id
        valid_mask = oof_frame[fold_col] == fold_id
        lr = LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)
        lr.fit(oof_frame.loc[train_mask, stacker_columns], labels[train_mask])
        stacker_probs[valid_mask] = lr.predict_proba(oof_frame.loc[valid_mask, stacker_columns])[:, 1]

    if threshold_grid is None:
        threshold_grid = np.arange(0.05, 0.50, 0.01)

    best_f1 = 0.0
    best_thresh = 0.10
    for thresh in threshold_grid:
        preds = (stacker_probs >= thresh).astype(int)
        f1 = float(f1_score(labels, preds, zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = float(thresh)

    return best_f1, best_thresh


def run_hpo_study(
    n_trials: int = 30,
    timeout: int | None = None,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    """Run Optuna HPO study for CatBoost Base A hyperparameters.

    Returns dict with best_params, best_f1, best_threshold, and study summary.
    """
    logger.info("Loading dataset and building splits...")
    dataset = _load_dataset("full")
    label_frame = _label_frame(dataset)

    primary_split = build_primary_transductive_splits(
        dataset, cutoff_tag="full", spec=PrimarySplitSpec(), write_outputs=False,
    )
    split_frame = dataset[["user_id", "status", "cohort"]].copy()
    split_frame = split_frame.merge(primary_split[["user_id", "primary_fold"]], on="user_id", how="left")

    base_a_feature_columns = _label_free_feature_columns(dataset)
    assignments = iter_fold_assignments(primary_split, "primary_fold")

    # Pre-compute per-fold train/valid frames (shared across trials)
    fold_data = []
    for fold_id, train_users, valid_users in assignments:
        train_mask = dataset["user_id"].astype(int).isin(train_users)
        valid_mask = dataset["user_id"].astype(int).isin(valid_users)
        fold_data.append({
            "fold_id": fold_id,
            "train_frame": dataset[train_mask].copy(),
            "valid_frame": dataset[valid_mask].copy(),
        })
    logger.info(f"Prepared {len(fold_data)} folds, {len(base_a_feature_columns)} features")

    trial_results: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        params = {
            "depth": trial.suggest_int("depth", 4, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            # v34: extend l2 upper bound (best was 25.7 near old limit of 30)
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 60.0, log=True),
            "random_strength": trial.suggest_float("random_strength", 0.1, 10.0, log=True),
            # v34: extend bagging upper bound (best was 3.89 near old limit of 5)
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 8.0),
            "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
            # v34: extend min_data_in_leaf (more regularization options)
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 100),
            "iterations": 1500,
            "early_stopping_rounds": 100,
            "max_class_weight": trial.suggest_float("max_class_weight", 5.0, 20.0),
        }

        t0 = time.time()
        oof_rows = []
        for fd in fold_data:
            try:
                val_probs, _ = _fit_catboost_trial(
                    fd["train_frame"], fd["valid_frame"],
                    base_a_feature_columns, params,
                )
            except Exception as exc:
                logger.warning(f"Fold {fd['fold_id']} failed: {exc}")
                return 0.0  # Failed trial

            fold_frame = fd["valid_frame"][["user_id", "status"]].copy()
            fold_frame["primary_fold"] = fd["fold_id"]
            fold_frame["base_a_probability"] = np.asarray(val_probs, dtype=float)
            fold_frame["rule_score"] = pd.to_numeric(
                fd["valid_frame"]["rule_score"], errors="coerce"
            ).fillna(0.0).to_numpy()
            fold_frame["anomaly_score"] = pd.to_numeric(
                fd["valid_frame"]["anomaly_score"], errors="coerce"
            ).fillna(0.0).to_numpy()
            oof_rows.append(fold_frame)

        oof_frame = pd.concat(oof_rows, ignore_index=True)
        f1, threshold = _compute_oof_f1(oof_frame, _HPO_STACKER_COLUMNS)
        elapsed = time.time() - t0

        result = {
            "trial": trial.number,
            "f1": f1,
            "threshold": threshold,
            "elapsed_s": round(elapsed, 1),
            **{k: v for k, v in params.items() if k not in ("iterations", "early_stopping_rounds")},
        }
        trial_results.append(result)
        logger.info(
            f"Trial {trial.number}: F1={f1:.4f} thr={threshold:.2f} "
            f"depth={params['depth']} lr={params['learning_rate']:.4f} "
            f"l2={params['l2_leaf_reg']:.2f} ({elapsed:.0f}s)"
        )
        # Save intermediate best after every trial so downstream runs can use
        # the best-so-far even if the study hasn't fully completed yet.
        _best_row = max(trial_results, key=lambda r: r["f1"])
        _interim = {
            "best_params": {k: v for k, v in _best_row.items() if k not in ("trial", "f1", "threshold", "elapsed_s")},
            "best_f1": _best_row["f1"],
            "best_trial_number": _best_row["trial"],
            "n_trials": len(trial_results),
            "trial_results": sorted(trial_results, key=lambda x: -x["f1"]),
        }
        try:
            save_json(_interim, load_official_paths().feature_dir / "hpo_best_params.json")
        except Exception:
            pass
        return f1

    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(10, n_trials // 3))
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        study_name="bitoguard_catboost_base_a_hpo",
    )

    # Enqueue the current default as the first trial (ensures we have a baseline)
    study.enqueue_trial({
        "depth": 7,
        "learning_rate": 0.05,
        "l2_leaf_reg": 3.0,
        "random_strength": 1.0,
        "bagging_temperature": 1.0,
        "border_count": 254,
        "min_data_in_leaf": 1,
        "max_class_weight": 10.0,
    })

    study.optimize(objective, n_trials=n_trials, timeout=timeout)

    best = study.best_trial
    best_params = dict(best.params)
    best_f1 = best.value

    # Save results
    paths = load_official_paths()
    output = {
        "best_params": best_params,
        "best_f1": best_f1,
        "best_trial_number": best.number,
        "n_trials": len(study.trials),
        "trial_results": sorted(trial_results, key=lambda x: -x["f1"]),
    }
    output_path = paths.feature_dir / "hpo_best_params.json"
    save_json(output, output_path)
    logger.info(f"Best F1={best_f1:.4f} at trial {best.number}")
    logger.info(f"Best params: {json.dumps(best_params, indent=2)}")
    logger.info(f"Saved to {output_path}")
    return output


def load_hpo_best_params() -> dict[str, Any] | None:
    """Load best HPO params if available. Returns None if not found."""
    paths = load_official_paths()
    path = paths.feature_dir / "hpo_best_params.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("best_params")


def main() -> None:
    parser = argparse.ArgumentParser(description="CatBoost Base A hyperparameter optimization")
    parser.add_argument("--n-trials", type=int, default=30, help="Number of Optuna trials")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED, help="Random seed")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    result = run_hpo_study(n_trials=args.n_trials, timeout=args.timeout, seed=args.seed)
    print(f"\n=== HPO Complete ===")
    print(f"Best F1: {result['best_f1']:.4f}")
    print(f"Best params: {json.dumps(result['best_params'], indent=2)}")
    print(f"Trials: {result['n_trials']}")


if __name__ == "__main__":
    main()
