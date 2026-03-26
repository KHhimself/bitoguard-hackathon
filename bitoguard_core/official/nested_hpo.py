"""巢狀交叉驗證 + 超參數最佳化 (Nested CV with HPO)。

外層迴圈: 5-fold StratifiedGroupKFold
  對每個外層 fold k:
    outer_train = folds != k
    outer_valid = fold == k

    內層 HPO (僅在 outer_train 上執行):
      內層切割: 3-fold StratifiedGroupKFold
      CatBoost HPO: 30 trials, Optuna TPE
      LightGBM HPO: 30 trials, Optuna TPE
      XGBoost HPO: 30 trials, Optuna TPE

    以最佳參數在完整 outer_train 上訓練:
      Base A: CatBoost x 4 seeds
      Base D: LightGBM x 3 seeds
      Base E: XGBoost x 2 seeds
      Base B: Transductive CatBoost (預設參數)
      C&S: Correct-and-Smooth

    預測 outer_valid -> OOF 預測
    Inner-fold selection (混合、校正、閾值)
    蒐集預測結果

  串接 -> 最終巢狀 OOF
  計算指標

Usage:
    cd bitoguard_core && source .venv/bin/activate

    # 單一 fold:
    PYTHONPATH=. python -m official.nested_hpo --outer-fold 0 --n-trials 30 --inner-folds 3

    # 所有 folds:
    PYTHONPATH=. python -m official.nested_hpo --all --n-trials 30

    # 彙總所有 fold 結果:
    PYTHONPATH=. python -m official.nested_hpo --aggregate
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold

try:
    import optuna
except ImportError:
    raise ImportError(
        "optuna>=3.0 is required for nested HPO. "
        "Install with: pip install 'optuna>=3.0'"
    )

from hardware import (
    catboost_runtime_params,
    lightgbm_runtime_params,
    xgboost_runtime_params,
    hardware_profile,
)
from official.common import (
    RANDOM_SEED,
    encode_frame,
    load_official_paths,
    save_json,
)
from official.inner_fold_selection import select_and_apply_inner_fold
from official.stacking import STACKER_FEATURE_COLUMNS, build_stacker_oof
from official.train import (
    LABEL_FREE_EXCLUDED_COLUMNS,
    _load_dataset,
    _label_frame,
    _label_free_feature_columns,
    run_transductive_oof_pipeline,
)
from official.transductive_validation import (
    PrimarySplitSpec,
    build_primary_transductive_splits,
    iter_fold_assignments,
)

logger = logging.getLogger(__name__)

# ── 多種子集成設定 (與 train.py 一致) ──
_BASE_A_SEEDS = [42, 52, 62, 72]   # CatBoost: 4 seeds
_BASE_D_SEEDS = [42, 123, 456]     # LightGBM: 3 seeds
_BASE_E_SEEDS = [42, 123]          # XGBoost: 2 seeds

# ── 巢狀 HPO 輸出目錄 ──
_NESTED_HPO_DIR_NAME = "nested_hpo"


def _nested_hpo_dir() -> Path:
    """回傳巢狀 HPO 的根目錄。"""
    paths = load_official_paths()
    d = paths.feature_dir / _NESTED_HPO_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fold_dir(outer_fold: int) -> Path:
    """回傳指定外層 fold 的輸出目錄。"""
    d = _nested_hpo_dir() / f"fold_{outer_fold}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 內層 HPO: CatBoost trial
# ---------------------------------------------------------------------------

def _catboost_hpo_objective(
    trial: optuna.Trial,
    inner_folds_data: list[dict[str, Any]],
    feature_columns: list[str],
) -> float:
    """CatBoost 內層 HPO 目標函數 — 回傳平均內層驗證 F1。

    搜尋空間沿用 hpo.py 的設計。
    """
    from catboost import CatBoostClassifier

    params = {
        "depth": trial.suggest_int("depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 60.0, log=True),
        "random_strength": trial.suggest_float("random_strength", 0.1, 10.0, log=True),
        "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 8.0),
        "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 1, 100),
        "max_class_weight": trial.suggest_float("max_class_weight", 5.0, 20.0),
    }

    runtime_params = catboost_runtime_params()
    fold_f1_scores: list[float] = []

    for fd in inner_folds_data:
        train_frame = fd["train_frame"]
        valid_frame = fd["valid_frame"]

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
        weight_ratio = min(float(negatives) / positives, params["max_class_weight"])

        model_kwargs = dict(
            loss_function="Logloss",
            eval_metric="Logloss",
            class_weights=[1.0, weight_ratio],
            random_seed=RANDOM_SEED,
            verbose=False,
            iterations=1500,
            depth=params["depth"],
            learning_rate=params["learning_rate"],
            l2_leaf_reg=params["l2_leaf_reg"],
            random_strength=params["random_strength"],
            bagging_temperature=params["bagging_temperature"],
            border_count=params["border_count"],
            min_data_in_leaf=params["min_data_in_leaf"],
            **runtime_params,
        )

        model = CatBoostClassifier(**model_kwargs)
        try:
            model.fit(
                train_frame[feature_columns], y_train,
                cat_features=cat_features,
                eval_set=(valid_frame[feature_columns], y_valid),
                use_best_model=True,
                early_stopping_rounds=100,
            )
        except Exception:
            # GPU 失敗時回退到 CPU
            if runtime_params.get("task_type") != "GPU":
                return 0.0
            cpu_kwargs = {
                **model_kwargs,
                "task_type": "CPU",
                "thread_count": hardware_profile().cpu_threads,
            }
            cpu_kwargs.pop("devices", None)
            cpu_kwargs.pop("gpu_ram_part", None)
            cpu_kwargs.pop("boosting_type", None)
            model = CatBoostClassifier(**cpu_kwargs)
            try:
                model.fit(
                    train_frame[feature_columns], y_train,
                    cat_features=cat_features,
                    eval_set=(valid_frame[feature_columns], y_valid),
                    use_best_model=True,
                    early_stopping_rounds=100,
                )
            except Exception:
                return 0.0

        val_probs = model.predict_proba(valid_frame[feature_columns])[:, 1]
        # 在多個閾值上搜尋最佳 F1
        best_f1 = 0.0
        for thresh in np.arange(0.05, 0.50, 0.01):
            preds = (val_probs >= thresh).astype(int)
            f1 = float(f1_score(y_valid, preds, zero_division=0))
            if f1 > best_f1:
                best_f1 = f1
        fold_f1_scores.append(best_f1)

    return float(np.mean(fold_f1_scores))


# ---------------------------------------------------------------------------
# 內層 HPO: LightGBM trial
# ---------------------------------------------------------------------------

def _lgbm_hpo_objective(
    trial: optuna.Trial,
    inner_folds_data: list[dict[str, Any]],
    feature_columns: list[str],
) -> float:
    """LightGBM 內層 HPO 目標函數 — 回傳平均內層驗證 F1。"""
    from lightgbm import LGBMClassifier

    params = {
        "n_estimators": trial.suggest_int("n_estimators", 200, 800),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 63),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 30),
    }

    runtime_params = lightgbm_runtime_params()
    fold_f1_scores: list[float] = []

    for fd in inner_folds_data:
        train_frame = fd["train_frame"]
        valid_frame = fd["valid_frame"]

        x_train, encoded_columns = encode_frame(train_frame, feature_columns)
        y_train = train_frame["status"].astype(int)
        x_valid, _ = encode_frame(
            valid_frame, feature_columns, reference_columns=encoded_columns
        )
        y_valid = valid_frame["status"].astype(int)

        positives = max(1, int(y_train.sum()))
        negatives = max(1, len(y_train) - positives)

        model_kwargs = dict(
            n_estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
            num_leaves=params["num_leaves"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            min_child_weight=params["min_child_weight"],
            scale_pos_weight=negatives / positives,
            random_state=RANDOM_SEED,
            verbosity=-1,
            **runtime_params,
        )

        model = LGBMClassifier(**model_kwargs)
        try:
            model.fit(
                x_train, y_train,
                eval_set=[(x_valid, y_valid)],
                eval_metric="binary_logloss",
            )
        except Exception:
            # GPU 失敗時回退到 CPU
            if runtime_params.get("device_type") != "gpu":
                return 0.0
            cpu_kwargs = {
                **model_kwargs,
                "device_type": "cpu",
                "n_jobs": hardware_profile().cpu_threads,
            }
            model = LGBMClassifier(**cpu_kwargs)
            try:
                model.fit(
                    x_train, y_train,
                    eval_set=[(x_valid, y_valid)],
                    eval_metric="binary_logloss",
                )
            except Exception:
                return 0.0

        val_probs = model.predict_proba(x_valid)[:, 1]
        best_f1 = 0.0
        for thresh in np.arange(0.05, 0.50, 0.01):
            preds = (val_probs >= thresh).astype(int)
            f1 = float(f1_score(y_valid, preds, zero_division=0))
            if f1 > best_f1:
                best_f1 = f1
        fold_f1_scores.append(best_f1)

    return float(np.mean(fold_f1_scores))


# ---------------------------------------------------------------------------
# 內層 HPO: XGBoost trial
# ---------------------------------------------------------------------------

def _xgb_hpo_objective(
    trial: optuna.Trial,
    inner_folds_data: list[dict[str, Any]],
    feature_columns: list[str],
) -> float:
    """XGBoost 內層 HPO 目標函數 — 回傳平均內層驗證 F1。

    搜尋空間以 modeling_xgb.py 的預設值為中心。
    """
    from xgboost import XGBClassifier

    params = {
        "n_estimators": trial.suggest_int("n_estimators", 500, 1500),
        "max_depth": trial.suggest_int("max_depth", 4, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.001, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 50.0, log=True),
        "min_child_weight": trial.suggest_float("min_child_weight", 1.0, 30.0),
    }

    runtime_params = xgboost_runtime_params()
    fold_f1_scores: list[float] = []

    for fd in inner_folds_data:
        train_frame = fd["train_frame"]
        valid_frame = fd["valid_frame"]

        x_train, encoded_columns = encode_frame(train_frame, feature_columns)
        y_train = train_frame["status"].astype(int)
        x_valid, _ = encode_frame(
            valid_frame, feature_columns, reference_columns=encoded_columns
        )
        y_valid = valid_frame["status"].astype(int)

        positives = max(1, int(y_train.sum()))
        negatives = max(1, len(y_train) - positives)
        scale_pos_weight = min(float(negatives) / positives, 15.0)

        model_kwargs = dict(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            learning_rate=params["learning_rate"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            reg_alpha=params["reg_alpha"],
            reg_lambda=params["reg_lambda"],
            min_child_weight=params["min_child_weight"],
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=RANDOM_SEED,
            verbosity=0,
            early_stopping_rounds=100,
            **runtime_params,
        )

        model = XGBClassifier(**model_kwargs)
        try:
            model.fit(x_train, y_train, eval_set=[(x_valid, y_valid)], verbose=False)
        except Exception:
            # GPU 失敗時回退到 CPU
            if runtime_params.get("device") != "cuda":
                return 0.0
            cpu_kwargs = {
                **model_kwargs,
                "device": "cpu",
                "tree_method": "hist",
            }
            cpu_kwargs.pop("n_jobs", None)
            model = XGBClassifier(**cpu_kwargs)
            try:
                model.fit(
                    x_train, y_train,
                    eval_set=[(x_valid, y_valid)],
                    verbose=False,
                )
            except Exception:
                return 0.0

        val_probs = model.predict_proba(x_valid)[:, 1]
        best_f1 = 0.0
        for thresh in np.arange(0.05, 0.50, 0.01):
            preds = (val_probs >= thresh).astype(int)
            f1 = float(f1_score(y_valid, preds, zero_division=0))
            if f1 > best_f1:
                best_f1 = f1
        fold_f1_scores.append(best_f1)

    return float(np.mean(fold_f1_scores))


# ---------------------------------------------------------------------------
# 內層 HPO 主函數: 對 outer_train 執行 3 個模型的 HPO
# ---------------------------------------------------------------------------

def _build_inner_folds(
    outer_train_frame: pd.DataFrame,
    feature_columns: list[str],
    n_inner_folds: int = 3,
    seed: int = RANDOM_SEED,
) -> list[dict[str, Any]]:
    """在 outer_train 上建立內層 StratifiedGroupKFold 切割。

    使用 user_id 作為 group (與 StratifiedKFold 相容)。
    """
    labeled = outer_train_frame[outer_train_frame["status"].notna()].copy()
    y = labeled["status"].astype(int)
    # 使用 user_id 作為 group，保證同一使用者不會跨 fold
    groups = labeled["user_id"].astype(int)

    splitter = StratifiedGroupKFold(
        n_splits=n_inner_folds, shuffle=True, random_state=seed
    )

    folds_data: list[dict[str, Any]] = []
    for fold_idx, (train_idx, valid_idx) in enumerate(
        splitter.split(labeled, y, groups)
    ):
        folds_data.append({
            "fold_id": fold_idx,
            "train_frame": labeled.iloc[train_idx].copy(),
            "valid_frame": labeled.iloc[valid_idx].copy(),
        })

    return folds_data


def _run_inner_hpo(
    outer_train_frame: pd.DataFrame,
    feature_columns: list[str],
    n_trials: int = 30,
    n_inner_folds: int = 3,
    seed: int = RANDOM_SEED,
) -> dict[str, dict[str, Any]]:
    """對三個基礎模型分別執行內層 HPO，回傳各模型最佳參數。

    Returns:
        dict，包含 "catboost", "lightgbm", "xgboost" 三組最佳參數與 F1。
    """
    inner_folds = _build_inner_folds(
        outer_train_frame, feature_columns,
        n_inner_folds=n_inner_folds, seed=seed,
    )
    logger.info(
        f"內層切割完成: {n_inner_folds} folds, "
        f"每 fold 約 {len(inner_folds[0]['train_frame'])} 筆訓練 / "
        f"{len(inner_folds[0]['valid_frame'])} 筆驗證"
    )

    results: dict[str, dict[str, Any]] = {}
    sampler_kwargs = dict(seed=seed, n_startup_trials=min(10, n_trials // 3))

    # ── CatBoost HPO ──
    logger.info(f"開始 CatBoost HPO ({n_trials} trials)...")
    t0 = time.time()
    cb_sampler = optuna.samplers.TPESampler(**sampler_kwargs)
    cb_study = optuna.create_study(
        direction="maximize",
        sampler=cb_sampler,
        study_name="nested_catboost_hpo",
    )
    # 加入預設基線 trial
    cb_study.enqueue_trial({
        "depth": 7,
        "learning_rate": 0.05,
        "l2_leaf_reg": 3.0,
        "random_strength": 1.0,
        "bagging_temperature": 1.0,
        "border_count": 254,
        "min_data_in_leaf": 1,
        "max_class_weight": 10.0,
    })
    cb_study.optimize(
        lambda trial: _catboost_hpo_objective(trial, inner_folds, feature_columns),
        n_trials=n_trials,
    )
    cb_elapsed = time.time() - t0
    results["catboost"] = {
        "best_params": dict(cb_study.best_trial.params),
        "best_f1": float(cb_study.best_value),
        "best_trial": cb_study.best_trial.number,
        "n_trials": len(cb_study.trials),
        "elapsed_s": round(cb_elapsed, 1),
        "study_trials": [
            {"number": t.number, "value": t.value, "params": t.params}
            for t in cb_study.trials if t.value is not None
        ],
    }
    logger.info(
        f"CatBoost HPO 完成: best F1={cb_study.best_value:.4f} "
        f"({cb_elapsed:.0f}s)"
    )

    # ── LightGBM HPO ──
    logger.info(f"開始 LightGBM HPO ({n_trials} trials)...")
    t0 = time.time()
    lgbm_sampler = optuna.samplers.TPESampler(**sampler_kwargs)
    lgbm_study = optuna.create_study(
        direction="maximize",
        sampler=lgbm_sampler,
        study_name="nested_lightgbm_hpo",
    )
    # 加入預設基線 trial
    lgbm_study.enqueue_trial({
        "n_estimators": 400,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "min_child_weight": 1,
    })
    lgbm_study.optimize(
        lambda trial: _lgbm_hpo_objective(trial, inner_folds, feature_columns),
        n_trials=n_trials,
    )
    lgbm_elapsed = time.time() - t0
    results["lightgbm"] = {
        "best_params": dict(lgbm_study.best_trial.params),
        "best_f1": float(lgbm_study.best_value),
        "best_trial": lgbm_study.best_trial.number,
        "n_trials": len(lgbm_study.trials),
        "elapsed_s": round(lgbm_elapsed, 1),
        "study_trials": [
            {"number": t.number, "value": t.value, "params": t.params}
            for t in lgbm_study.trials if t.value is not None
        ],
    }
    logger.info(
        f"LightGBM HPO 完成: best F1={lgbm_study.best_value:.4f} "
        f"({lgbm_elapsed:.0f}s)"
    )

    # ── XGBoost HPO ──
    logger.info(f"開始 XGBoost HPO ({n_trials} trials)...")
    t0 = time.time()
    xgb_sampler = optuna.samplers.TPESampler(**sampler_kwargs)
    xgb_study = optuna.create_study(
        direction="maximize",
        sampler=xgb_sampler,
        study_name="nested_xgboost_hpo",
    )
    # 加入預設基線 trial (基於 modeling_xgb.py 預設值)
    xgb_study.enqueue_trial({
        "n_estimators": 1500,
        "max_depth": 6,
        "learning_rate": 0.0585,
        "subsample": 0.812,
        "colsample_bytree": 0.881,
        "reg_alpha": 0.061,
        "reg_lambda": 5.707,
        "min_child_weight": 5.185,
    })
    xgb_study.optimize(
        lambda trial: _xgb_hpo_objective(trial, inner_folds, feature_columns),
        n_trials=n_trials,
    )
    xgb_elapsed = time.time() - t0
    results["xgboost"] = {
        "best_params": dict(xgb_study.best_trial.params),
        "best_f1": float(xgb_study.best_value),
        "best_trial": xgb_study.best_trial.number,
        "n_trials": len(xgb_study.trials),
        "elapsed_s": round(xgb_elapsed, 1),
        "study_trials": [
            {"number": t.number, "value": t.value, "params": t.params}
            for t in xgb_study.trials if t.value is not None
        ],
    }
    logger.info(
        f"XGBoost HPO 完成: best F1={xgb_study.best_value:.4f} "
        f"({xgb_elapsed:.0f}s)"
    )

    return results


# ---------------------------------------------------------------------------
# 單一外層 fold 的完整流程
# ---------------------------------------------------------------------------

def run_outer_fold(
    outer_fold: int,
    n_trials: int = 30,
    n_inner_folds: int = 3,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    """執行單一外層 fold 的巢狀 HPO 流程。

    Steps:
    1. 載入資料集，建立 5-fold 外層切割
    2. 取出 outer_train / outer_valid
    3. 在 outer_train 上執行內層 HPO (CatBoost/LightGBM/XGBoost)
    4. 以最佳參數 + run_transductive_oof_pipeline() 在 outer_train 上訓練
    5. 預測 outer_valid，蒐集 OOF 預測
    6. 執行 inner-fold selection (混合、校正、閾值)
    7. 儲存所有產出物

    Returns:
        包含 fold 結果的字典。
    """
    t_start = time.time()
    fold_output = _fold_dir(outer_fold)
    logger.info(f"=== 外層 fold {outer_fold} 開始 ===")
    logger.info(f"輸出目錄: {fold_output}")

    # ── 1. 載入資料集 ──
    logger.info("載入資料集...")
    dataset = _load_dataset("full")
    label_frame = _label_frame(dataset)
    feature_columns = _label_free_feature_columns(dataset)

    # ── 2. 建立外層 5-fold 切割 ──
    primary_split = build_primary_transductive_splits(
        dataset, cutoff_tag="full",
        spec=PrimarySplitSpec(), write_outputs=False,
    )
    assignments = iter_fold_assignments(primary_split, "primary_fold")

    # 取出目標 fold
    target_assignment = None
    for fold_id, train_users, valid_users in assignments:
        if fold_id == outer_fold:
            target_assignment = (fold_id, train_users, valid_users)
            break

    if target_assignment is None:
        raise ValueError(
            f"外層 fold {outer_fold} 不存在。可用的 fold: "
            f"{[a[0] for a in assignments]}"
        )

    _, outer_train_users, outer_valid_users = target_assignment
    outer_train_mask = dataset["user_id"].astype(int).isin(outer_train_users)
    outer_train_frame = dataset[outer_train_mask].copy()
    logger.info(
        f"外層切割: train={len(outer_train_users)} users, "
        f"valid={len(outer_valid_users)} users"
    )

    # ── 3. 內層 HPO ──
    logger.info("開始內層 HPO...")
    hpo_results = _run_inner_hpo(
        outer_train_frame, feature_columns,
        n_trials=n_trials,
        n_inner_folds=n_inner_folds,
        seed=seed,
    )

    # 儲存各模型 HPO 結果
    save_json(hpo_results["catboost"], fold_output / "catboost_hpo_study.json")
    save_json(hpo_results["lightgbm"], fold_output / "lightgbm_hpo_study.json")
    save_json(hpo_results["xgboost"], fold_output / "xgboost_hpo_study.json")

    best_params_all = {
        "catboost": hpo_results["catboost"]["best_params"],
        "lightgbm": hpo_results["lightgbm"]["best_params"],
        "xgboost": hpo_results["xgboost"]["best_params"],
    }
    save_json(best_params_all, fold_output / "best_params.json")
    logger.info(
        f"內層 HPO 完成 — CatBoost F1={hpo_results['catboost']['best_f1']:.4f}, "
        f"LightGBM F1={hpo_results['lightgbm']['best_f1']:.4f}, "
        f"XGBoost F1={hpo_results['xgboost']['best_f1']:.4f}"
    )

    # ── 4. 以最佳參數在完整 outer_train 上訓練 ──
    # 建立一個僅包含 outer_train 使用者的 split_frame (每個使用者都需要 fold)
    # 重新切割 outer_train 為內部 5-fold，供 run_transductive_oof_pipeline 使用
    logger.info("以最佳參數在 outer_train 上進行完整訓練...")

    # 為 outer_train 建立內部切割 (用於 run_transductive_oof_pipeline 的 OOF)
    outer_train_labeled = primary_split[
        primary_split["user_id"].astype(int).isin(outer_train_users)
    ].copy()

    # 將 HPO 最佳參數注入環境供 fit_catboost / fit_lgbm / fit_xgboost 使用
    # 注意: run_transductive_oof_pipeline 內部呼叫 fit_catboost 等函數
    # 我們需要透過環境或直接呼叫來傳遞最佳參數
    # 這裡直接呼叫 run_transductive_oof_pipeline，它會使用預設參數
    # 但我們會將 CatBoost 最佳參數作為 catboost_params 傳入 fit_catboost

    # 由於 run_transductive_oof_pipeline 的介面不直接接受 HPO 參數，
    # 我們需要直接實作訓練迴圈 (類似 train.py 的 run_transductive_oof_pipeline)

    from official.graph_dataset import build_transductive_graph
    from official.transductive_features import build_transductive_feature_frame
    from official.modeling import fit_catboost, fit_lgbm
    from official.modeling_xgb import fit_xgboost
    from official.correct_and_smooth import correct_and_smooth
    from official.graph_model import train_graphsage_model

    graph = build_transductive_graph(dataset)

    # 建立 outer_train 的 5-fold OOF 切割
    oof_split = build_primary_transductive_splits(
        outer_train_frame[outer_train_frame["status"].notna()].copy(),
        cutoff_tag="full",
        spec=PrimarySplitSpec(n_splits=5, random_state=seed),
        write_outputs=False,
    )

    oof_assignments = iter_fold_assignments(oof_split, "primary_fold")
    oof_rows: list[pd.DataFrame] = []

    # 準備 CatBoost 最佳參數 (來自 HPO)
    cb_best = hpo_results["catboost"]["best_params"].copy()
    # 移除非 CatBoost 原生參數
    cb_max_cw = cb_best.pop("max_class_weight", 10.0)
    catboost_hpo_params = {
        "depth": cb_best.get("depth", 7),
        "learning_rate": cb_best.get("learning_rate", 0.05),
        "l2_leaf_reg": cb_best.get("l2_leaf_reg", 3.0),
        "random_strength": cb_best.get("random_strength", 1.0),
        "bagging_temperature": cb_best.get("bagging_temperature", 1.0),
        "border_count": cb_best.get("border_count", 254),
        "min_data_in_leaf": cb_best.get("min_data_in_leaf", 1),
        "iterations": 1500,
        "early_stopping_rounds": 100,
        "max_class_weight": cb_max_cw,
    }

    # LightGBM 最佳參數
    lgbm_best = hpo_results["lightgbm"]["best_params"].copy()

    # XGBoost 最佳參數
    xgb_best = hpo_results["xgboost"]["best_params"].copy()

    for fold_id, train_users_inner, valid_users_inner in oof_assignments:
        logger.info(f"  外層 fold {outer_fold} — 內部 OOF fold {fold_id}")

        fold_train_labels = label_frame[
            label_frame["user_id"].astype(int).isin(train_users_inner)
        ].copy()
        transductive_features = build_transductive_feature_frame(
            graph, fold_train_labels
        )

        # 準備 label-free 和 transductive 資料框
        label_free_frame = dataset.copy()
        trans_cols = [c for c in transductive_features.columns if c != "user_id"]
        with_transductive_frame = dataset.merge(
            transductive_features, on="user_id", how="left"
        )
        with_transductive_frame[trans_cols] = (
            with_transductive_frame[trans_cols].fillna(0.0)
        )

        train_lf = label_free_frame[
            label_free_frame["user_id"].astype(int).isin(train_users_inner)
        ].copy()
        valid_lf = label_free_frame[
            label_free_frame["user_id"].astype(int).isin(valid_users_inner)
        ].copy()
        train_td = with_transductive_frame[
            with_transductive_frame["user_id"].astype(int).isin(train_users_inner)
        ].copy()
        valid_td = with_transductive_frame[
            with_transductive_frame["user_id"].astype(int).isin(valid_users_inner)
        ].copy()

        # Base A: CatBoost x 4 seeds (使用 HPO 最佳參數)
        base_a_val_probs = []
        base_a_models = []
        for _seed in _BASE_A_SEEDS:
            _fit = fit_catboost(
                train_lf, valid_lf, feature_columns,
                focal_gamma=2.0,
                catboost_params=catboost_hpo_params.copy(),
                random_seed=_seed,
            )
            base_a_val_probs.append(_fit.validation_probabilities)
            base_a_models.append(_fit.model)
        base_a_probs = np.mean(base_a_val_probs, axis=0)

        # Base B: Transductive CatBoost (預設參數)
        base_b_columns = feature_columns + trans_cols
        base_b_params = {"task_type": "CPU", "l2_leaf_reg": 5.0}
        base_b_fit = fit_catboost(
            train_td, valid_td, base_b_columns,
            focal_gamma=2.0, catboost_params=base_b_params,
        )

        # Base D: LightGBM x 3 seeds (使用 HPO 最佳參數)
        base_d_val_probs = []
        for _seed_d in _BASE_D_SEEDS:
            _lgbm_fit = fit_lgbm(
                train_lf, valid_lf, feature_columns, random_seed=_seed_d,
            )
            # 注意: fit_lgbm 不接受自訂參數，HPO 參數透過模型級別傳遞
            # 這裡直接使用 LGBMClassifier 以傳入 HPO 最佳參數
            base_d_val_probs.append(_lgbm_fit.validation_probabilities)

        # 使用 HPO 最佳參數重新訓練 LightGBM
        from lightgbm import LGBMClassifier

        base_d_val_probs_hpo = []
        for _seed_d in _BASE_D_SEEDS:
            x_train_d, enc_cols_d = encode_frame(train_lf, feature_columns)
            y_train_d = train_lf["status"].astype(int)
            x_valid_d, _ = encode_frame(
                valid_lf, feature_columns, reference_columns=enc_cols_d
            )
            y_valid_d = valid_lf["status"].astype(int)
            pos_d = max(1, int(y_train_d.sum()))
            neg_d = max(1, len(y_train_d) - pos_d)
            _lgbm_rt = lightgbm_runtime_params()
            lgbm_model = LGBMClassifier(
                n_estimators=lgbm_best.get("n_estimators", 400),
                learning_rate=lgbm_best.get("learning_rate", 0.05),
                num_leaves=lgbm_best.get("num_leaves", 31),
                subsample=lgbm_best.get("subsample", 0.9),
                colsample_bytree=lgbm_best.get("colsample_bytree", 0.9),
                min_child_weight=lgbm_best.get("min_child_weight", 1),
                scale_pos_weight=neg_d / pos_d,
                random_state=_seed_d,
                verbosity=-1,
                **_lgbm_rt,
            )
            try:
                lgbm_model.fit(
                    x_train_d, y_train_d,
                    eval_set=[(x_valid_d, y_valid_d)],
                    eval_metric="binary_logloss",
                )
            except Exception:
                if _lgbm_rt.get("device_type") != "gpu":
                    raise
                lgbm_model = LGBMClassifier(
                    n_estimators=lgbm_best.get("n_estimators", 400),
                    learning_rate=lgbm_best.get("learning_rate", 0.05),
                    num_leaves=lgbm_best.get("num_leaves", 31),
                    subsample=lgbm_best.get("subsample", 0.9),
                    colsample_bytree=lgbm_best.get("colsample_bytree", 0.9),
                    min_child_weight=lgbm_best.get("min_child_weight", 1),
                    scale_pos_weight=neg_d / pos_d,
                    random_state=_seed_d,
                    verbosity=-1,
                    n_jobs=hardware_profile().cpu_threads,
                )
                lgbm_model.fit(
                    x_train_d, y_train_d,
                    eval_set=[(x_valid_d, y_valid_d)],
                    eval_metric="binary_logloss",
                )
            base_d_val_probs_hpo.append(
                lgbm_model.predict_proba(x_valid_d)[:, 1].tolist()
            )
        base_d_probs = np.mean(base_d_val_probs_hpo, axis=0)

        # Base E: XGBoost x 2 seeds (使用 HPO 最佳參數)
        base_e_val_probs = []
        base_e_models = []
        for _seed_e in _BASE_E_SEEDS:
            _xgb_fit = fit_xgboost(
                train_lf, valid_lf, feature_columns,
                params=xgb_best, random_seed=_seed_e,
            )
            base_e_val_probs.append(_xgb_fit.validation_probabilities)
            base_e_models.append(_xgb_fit.model)
        base_e_probs = np.mean(base_e_val_probs, axis=0)

        # GNN (跳過以節省時間，設定 SKIP_GNN=1 時)
        import os as _gnn_os
        _skip_gnn = _gnn_os.environ.get("SKIP_GNN", "0") == "1"
        if _skip_gnn:
            gnn_probs = np.zeros(len(valid_lf))
            logger.info(f"    GNN 已跳過 (SKIP_GNN=1)")
        else:
            graph_fit = train_graphsage_model(
                graph,
                label_frame=label_frame,
                train_user_ids=train_users_inner,
                valid_user_ids=valid_users_inner,
                max_epochs=40,
                hidden_dim=128,
            )
            gnn_probs = np.asarray(graph_fit.validation_probabilities, dtype=float)
            try:
                import torch as _torch
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
            except Exception:
                pass

        # Correct-and-Smooth (C&S)
        cs_train_probs = np.mean(
            [m.predict_proba(train_lf[feature_columns])[:, 1]
             for m in base_a_models],
            axis=0,
        )
        cs_val_probs_raw = base_a_probs.copy()
        cs_base_probs: dict[int, float] = {}
        for uid, prob in zip(
            train_lf["user_id"].astype(int), cs_train_probs
        ):
            cs_base_probs[int(uid)] = float(prob)
        for uid, prob in zip(
            valid_lf["user_id"].astype(int), cs_val_probs_raw
        ):
            cs_base_probs[int(uid)] = float(prob)

        # 包含未標記使用者
        all_labeled_ids = set(train_users_inner) | set(valid_users_inner)
        unlabeled_frame = label_free_frame[
            ~label_free_frame["user_id"].astype(int).isin(all_labeled_ids)
        ]
        if len(unlabeled_frame) > 0:
            unlabeled_probs = np.mean(
                [m.predict_proba(unlabeled_frame[feature_columns])[:, 1]
                 for m in base_a_models],
                axis=0,
            )
            for uid, prob in zip(
                unlabeled_frame["user_id"].astype(int), unlabeled_probs
            ):
                cs_base_probs[int(uid)] = float(prob)

        cs_train_labels: dict[int, float] = dict(zip(
            fold_train_labels["user_id"].astype(int),
            fold_train_labels["status"].astype(float),
        ))
        cs_result = correct_and_smooth(
            graph, cs_train_labels, cs_base_probs,
            alpha_correct=0.5, alpha_smooth=0.5,
            n_correct_iter=50, n_smooth_iter=50,
        )
        val_ids = valid_lf["user_id"].astype(int).tolist()
        cs_val_probs = np.array(
            [cs_result.get(int(uid), float(p))
             for uid, p in zip(val_ids, cs_val_probs_raw)],
            dtype=float,
        )

        # 組合 fold 預測結果
        fold_frame = valid_lf[["user_id", "status"]].copy()
        fold_frame["primary_fold"] = fold_id
        fold_frame["base_a_probability"] = base_a_probs
        fold_frame["base_c_s_probability"] = cs_val_probs
        fold_frame["base_b_probability"] = np.asarray(
            base_b_fit.validation_probabilities, dtype=float
        )
        fold_frame["base_c_probability"] = gnn_probs
        fold_frame["base_d_probability"] = base_d_probs
        fold_frame["base_e_probability"] = base_e_probs
        fold_frame["rule_score"] = (
            pd.to_numeric(valid_lf["rule_score"], errors="coerce").fillna(0.0).to_numpy()
            if "rule_score" in valid_lf.columns
            else np.zeros(len(valid_lf))
        )
        fold_frame["anomaly_score"] = (
            pd.to_numeric(valid_lf["anomaly_score"], errors="coerce").fillna(0.0).to_numpy()
            if "anomaly_score" in valid_lf.columns
            else np.zeros(len(valid_lf))
        )
        fold_frame["crypto_anomaly_score"] = (
            pd.to_numeric(valid_lf["crypto_anomaly_score"], errors="coerce").fillna(0.0).to_numpy()
            if "crypto_anomaly_score" in valid_lf.columns
            else np.zeros(len(valid_lf))
        )
        fold_frame["anomaly_score_segmented"] = (
            pd.to_numeric(valid_lf["anomaly_score_segmented"], errors="coerce").fillna(0.0).to_numpy()
            if "anomaly_score_segmented" in valid_lf.columns
            else np.zeros(len(valid_lf))
        )
        oof_rows.append(fold_frame)

    # 合併 outer_train 上的 OOF
    train_oof = (
        pd.concat(oof_rows, ignore_index=True)
        .sort_values("user_id")
        .reset_index(drop=True)
    )

    # ── 5. 在完整 outer_train 上訓練最終模型，預測 outer_valid ──
    logger.info("在完整 outer_train 上訓練最終模型，預測 outer_valid...")

    # 準備 outer_valid 資料
    outer_valid_frame = dataset[
        dataset["user_id"].astype(int).isin(outer_valid_users)
    ].copy()

    # 準備 transductive features (使用 outer_train 的所有標籤)
    outer_train_labels = label_frame[
        label_frame["user_id"].astype(int).isin(outer_train_users)
    ].copy()
    final_transductive = build_transductive_feature_frame(
        graph, outer_train_labels
    )
    final_trans_cols = [c for c in final_transductive.columns if c != "user_id"]

    final_label_free = dataset.copy()
    final_with_td = dataset.merge(final_transductive, on="user_id", how="left")
    final_with_td[final_trans_cols] = final_with_td[final_trans_cols].fillna(0.0)

    train_lf_final = final_label_free[
        final_label_free["user_id"].astype(int).isin(outer_train_users)
    ].copy()
    valid_lf_final = final_label_free[
        final_label_free["user_id"].astype(int).isin(outer_valid_users)
    ].copy()
    train_td_final = final_with_td[
        final_with_td["user_id"].astype(int).isin(outer_train_users)
    ].copy()
    valid_td_final = final_with_td[
        final_with_td["user_id"].astype(int).isin(outer_valid_users)
    ].copy()

    # Base A: CatBoost x 4 seeds (HPO 最佳參數)
    final_a_probs = []
    final_a_models = []
    for _seed in _BASE_A_SEEDS:
        _fit = fit_catboost(
            train_lf_final, valid_lf_final, feature_columns,
            focal_gamma=2.0,
            catboost_params=catboost_hpo_params.copy(),
            random_seed=_seed,
        )
        final_a_probs.append(_fit.validation_probabilities)
        final_a_models.append(_fit.model)
    outer_valid_base_a = np.mean(final_a_probs, axis=0)

    # Base B: Transductive CatBoost
    final_b_columns = feature_columns + final_trans_cols
    final_b_fit = fit_catboost(
        train_td_final, valid_td_final, final_b_columns,
        focal_gamma=2.0, catboost_params={"task_type": "CPU", "l2_leaf_reg": 5.0},
    )

    # Base D: LightGBM x 3 seeds (HPO 最佳參數)
    final_d_probs = []
    for _seed_d in _BASE_D_SEEDS:
        x_tr_d, enc_d = encode_frame(train_lf_final, feature_columns)
        y_tr_d = train_lf_final["status"].astype(int)
        x_va_d, _ = encode_frame(
            valid_lf_final, feature_columns, reference_columns=enc_d
        )
        y_va_d = valid_lf_final["status"].astype(int)
        pos_d = max(1, int(y_tr_d.sum()))
        neg_d = max(1, len(y_tr_d) - pos_d)
        _lgbm_rt = lightgbm_runtime_params()
        lgbm_final = LGBMClassifier(
            n_estimators=lgbm_best.get("n_estimators", 400),
            learning_rate=lgbm_best.get("learning_rate", 0.05),
            num_leaves=lgbm_best.get("num_leaves", 31),
            subsample=lgbm_best.get("subsample", 0.9),
            colsample_bytree=lgbm_best.get("colsample_bytree", 0.9),
            min_child_weight=lgbm_best.get("min_child_weight", 1),
            scale_pos_weight=neg_d / pos_d,
            random_state=_seed_d,
            verbosity=-1,
            **_lgbm_rt,
        )
        try:
            lgbm_final.fit(
                x_tr_d, y_tr_d,
                eval_set=[(x_va_d, y_va_d)],
                eval_metric="binary_logloss",
            )
        except Exception:
            if _lgbm_rt.get("device_type") != "gpu":
                raise
            lgbm_final = LGBMClassifier(
                n_estimators=lgbm_best.get("n_estimators", 400),
                learning_rate=lgbm_best.get("learning_rate", 0.05),
                num_leaves=lgbm_best.get("num_leaves", 31),
                subsample=lgbm_best.get("subsample", 0.9),
                colsample_bytree=lgbm_best.get("colsample_bytree", 0.9),
                min_child_weight=lgbm_best.get("min_child_weight", 1),
                scale_pos_weight=neg_d / pos_d,
                random_state=_seed_d,
                verbosity=-1,
                n_jobs=hardware_profile().cpu_threads,
            )
            lgbm_final.fit(
                x_tr_d, y_tr_d,
                eval_set=[(x_va_d, y_va_d)],
                eval_metric="binary_logloss",
            )
        final_d_probs.append(lgbm_final.predict_proba(x_va_d)[:, 1].tolist())
    outer_valid_base_d = np.mean(final_d_probs, axis=0)

    # Base E: XGBoost x 2 seeds (HPO 最佳參數)
    final_e_probs = []
    final_e_models = []
    for _seed_e in _BASE_E_SEEDS:
        _xgb_fit = fit_xgboost(
            train_lf_final, valid_lf_final, feature_columns,
            params=xgb_best, random_seed=_seed_e,
        )
        final_e_probs.append(_xgb_fit.validation_probabilities)
        final_e_models.append(_xgb_fit.model)
    outer_valid_base_e = np.mean(final_e_probs, axis=0)

    # GNN
    if _skip_gnn:
        outer_valid_gnn = np.zeros(len(valid_lf_final))
    else:
        graph_fit_final = train_graphsage_model(
            graph,
            label_frame=label_frame,
            train_user_ids=outer_train_users,
            valid_user_ids=outer_valid_users,
            max_epochs=40,
            hidden_dim=128,
        )
        outer_valid_gnn = np.asarray(
            graph_fit_final.validation_probabilities, dtype=float
        )
        try:
            import torch as _torch
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass

    # C&S
    cs_train_probs_final = np.mean(
        [m.predict_proba(train_lf_final[feature_columns])[:, 1]
         for m in final_a_models],
        axis=0,
    )
    cs_val_raw_final = outer_valid_base_a.copy()
    cs_probs_final: dict[int, float] = {}
    for uid, prob in zip(
        train_lf_final["user_id"].astype(int), cs_train_probs_final
    ):
        cs_probs_final[int(uid)] = float(prob)
    for uid, prob in zip(
        valid_lf_final["user_id"].astype(int), cs_val_raw_final
    ):
        cs_probs_final[int(uid)] = float(prob)

    # 未標記使用者
    all_outer_ids = set(outer_train_users) | set(outer_valid_users)
    unlabeled_final = final_label_free[
        ~final_label_free["user_id"].astype(int).isin(all_outer_ids)
    ]
    if len(unlabeled_final) > 0:
        unlabeled_probs_final = np.mean(
            [m.predict_proba(unlabeled_final[feature_columns])[:, 1]
             for m in final_a_models],
            axis=0,
        )
        for uid, prob in zip(
            unlabeled_final["user_id"].astype(int), unlabeled_probs_final
        ):
            cs_probs_final[int(uid)] = float(prob)

    cs_train_labels_final: dict[int, float] = dict(zip(
        outer_train_labels["user_id"].astype(int),
        outer_train_labels["status"].astype(float),
    ))
    cs_result_final = correct_and_smooth(
        graph, cs_train_labels_final, cs_probs_final,
        alpha_correct=0.5, alpha_smooth=0.5,
        n_correct_iter=50, n_smooth_iter=50,
    )
    val_ids_final = valid_lf_final["user_id"].astype(int).tolist()
    cs_val_final = np.array(
        [cs_result_final.get(int(uid), float(p))
         for uid, p in zip(val_ids_final, cs_val_raw_final)],
        dtype=float,
    )

    # 組合 outer_valid 預測
    outer_valid_pred = valid_lf_final[["user_id", "status"]].copy()
    outer_valid_pred["outer_fold"] = outer_fold
    outer_valid_pred["primary_fold"] = outer_fold  # 用於 inner_fold_selection
    outer_valid_pred["base_a_probability"] = outer_valid_base_a
    outer_valid_pred["base_c_s_probability"] = cs_val_final
    outer_valid_pred["base_b_probability"] = np.asarray(
        final_b_fit.validation_probabilities, dtype=float
    )
    outer_valid_pred["base_c_probability"] = outer_valid_gnn
    outer_valid_pred["base_d_probability"] = outer_valid_base_d
    outer_valid_pred["base_e_probability"] = outer_valid_base_e
    outer_valid_pred["rule_score"] = (
        pd.to_numeric(valid_lf_final["rule_score"], errors="coerce").fillna(0.0).to_numpy()
        if "rule_score" in valid_lf_final.columns
        else np.zeros(len(valid_lf_final))
    )
    outer_valid_pred["anomaly_score"] = (
        pd.to_numeric(valid_lf_final["anomaly_score"], errors="coerce").fillna(0.0).to_numpy()
        if "anomaly_score" in valid_lf_final.columns
        else np.zeros(len(valid_lf_final))
    )
    outer_valid_pred["crypto_anomaly_score"] = (
        pd.to_numeric(valid_lf_final["crypto_anomaly_score"], errors="coerce").fillna(0.0).to_numpy()
        if "crypto_anomaly_score" in valid_lf_final.columns
        else np.zeros(len(valid_lf_final))
    )
    outer_valid_pred["anomaly_score_segmented"] = (
        pd.to_numeric(valid_lf_final["anomaly_score_segmented"], errors="coerce").fillna(0.0).to_numpy()
        if "anomaly_score_segmented" in valid_lf_final.columns
        else np.zeros(len(valid_lf_final))
    )

    # ── 6. Inner-fold selection (混合、校正、閾值) ──
    logger.info("執行 inner-fold selection (混合、校正、閾值)...")

    # 使用 train_oof 作為訓練集，outer_valid_pred 作為驗證集
    stacker_cols = [c for c in STACKER_FEATURE_COLUMNS if c in train_oof.columns]
    selected_valid, selection_meta = select_and_apply_inner_fold(
        train_oof, outer_valid_pred,
        fold_column="primary_fold",
        stacker_feature_columns=stacker_cols,
    )
    logger.info(
        f"Inner-fold selection 完成: "
        f"threshold={selection_meta['selected_threshold']:.4f}"
    )

    # ── 7. 計算 fold 指標並儲存 ──
    valid_labels = selected_valid["status"].astype(int).to_numpy()
    valid_probs = selected_valid["submission_probability"].to_numpy()

    # 搜尋最佳 F1 閾值
    best_f1 = 0.0
    best_thresh = 0.10
    for thresh in np.arange(0.05, 0.80, 0.01):
        preds = (valid_probs >= thresh).astype(int)
        f1 = float(f1_score(valid_labels, preds, zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = float(thresh)

    # 以最佳閾值計算完整指標
    final_preds = (valid_probs >= best_thresh).astype(int)
    fold_metrics = {
        "outer_fold": outer_fold,
        "n_valid": int(len(valid_labels)),
        "n_positive": int(valid_labels.sum()),
        "n_negative": int((1 - valid_labels).sum()),
        "best_f1": float(best_f1),
        "best_threshold": float(best_thresh),
        "precision": float(precision_score(valid_labels, final_preds, zero_division=0)),
        "recall": float(recall_score(valid_labels, final_preds, zero_division=0)),
        "auc_roc": float(roc_auc_score(valid_labels, valid_probs)) if valid_labels.sum() > 0 else 0.0,
        "average_precision": float(average_precision_score(valid_labels, valid_probs)) if valid_labels.sum() > 0 else 0.0,
        "hpo_catboost_f1": hpo_results["catboost"]["best_f1"],
        "hpo_lightgbm_f1": hpo_results["lightgbm"]["best_f1"],
        "hpo_xgboost_f1": hpo_results["xgboost"]["best_f1"],
        "selection_meta": selection_meta,
        "elapsed_s": round(time.time() - t_start, 1),
    }

    # 儲存產出物
    selected_valid.to_parquet(fold_output / "predictions.parquet", index=False)
    save_json(fold_metrics, fold_output / "metrics.json")
    save_json(best_params_all, fold_output / "best_params.json")

    logger.info(
        f"=== 外層 fold {outer_fold} 完成 ===\n"
        f"  F1={best_f1:.4f} (threshold={best_thresh:.2f})\n"
        f"  Precision={fold_metrics['precision']:.4f}, "
        f"Recall={fold_metrics['recall']:.4f}\n"
        f"  AUC-ROC={fold_metrics['auc_roc']:.4f}, "
        f"AP={fold_metrics['average_precision']:.4f}\n"
        f"  耗時: {fold_metrics['elapsed_s']:.0f}s"
    )

    return fold_metrics


# ---------------------------------------------------------------------------
# 彙總所有外層 fold 結果
# ---------------------------------------------------------------------------

def aggregate_nested_results() -> dict[str, Any]:
    """載入所有外層 fold 的預測結果，計算匯總指標。

    Returns:
        包含匯總指標與每個 fold 指標的字典。
    """
    root = _nested_hpo_dir()
    fold_dirs = sorted(root.glob("fold_*"))

    if not fold_dirs:
        raise FileNotFoundError(
            f"找不到任何 fold 目錄: {root}/fold_*"
        )

    all_predictions: list[pd.DataFrame] = []
    all_metrics: list[dict[str, Any]] = []

    for fd in fold_dirs:
        pred_path = fd / "predictions.parquet"
        metrics_path = fd / "metrics.json"

        if not pred_path.exists():
            logger.warning(f"跳過 {fd.name}: predictions.parquet 不存在")
            continue
        if not metrics_path.exists():
            logger.warning(f"跳過 {fd.name}: metrics.json 不存在")
            continue

        preds = pd.read_parquet(pred_path)
        all_predictions.append(preds)

        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics = json.load(f)
        all_metrics.append(metrics)

    if not all_predictions:
        raise FileNotFoundError(
            "沒有找到任何有效的 fold 結果。"
            "請先執行 --all 或 --outer-fold 來產生結果。"
        )

    # 串接所有 fold 的預測
    pooled = (
        pd.concat(all_predictions, ignore_index=True)
        .sort_values("user_id")
        .reset_index(drop=True)
    )

    # 檢查是否有重複的 user_id
    dup_count = pooled["user_id"].duplicated().sum()
    if dup_count > 0:
        logger.warning(f"偵測到 {dup_count} 個重複的 user_id，取最後出現的預測")
        pooled = pooled.drop_duplicates(subset=["user_id"], keep="last")

    # 計算匯總指標
    labels = pooled["status"].astype(int).to_numpy()
    probs = pooled["submission_probability"].to_numpy()

    # 搜尋全域最佳 F1 閾值
    best_f1 = 0.0
    best_thresh = 0.10
    for thresh in np.arange(0.05, 0.80, 0.01):
        preds = (probs >= thresh).astype(int)
        f1 = float(f1_score(labels, preds, zero_division=0))
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = float(thresh)

    final_preds = (probs >= best_thresh).astype(int)

    pooled_metrics = {
        "n_folds": len(all_metrics),
        "n_total": int(len(labels)),
        "n_positive": int(labels.sum()),
        "n_negative": int((1 - labels).sum()),
        "pooled_f1": float(best_f1),
        "pooled_threshold": float(best_thresh),
        "pooled_precision": float(precision_score(labels, final_preds, zero_division=0)),
        "pooled_recall": float(recall_score(labels, final_preds, zero_division=0)),
        "pooled_auc_roc": float(roc_auc_score(labels, probs)) if labels.sum() > 0 else 0.0,
        "pooled_average_precision": float(average_precision_score(labels, probs)) if labels.sum() > 0 else 0.0,
    }

    # 每個 fold 的指標摘要
    per_fold_f1 = [m.get("best_f1", 0.0) for m in all_metrics]
    per_fold_auc = [m.get("auc_roc", 0.0) for m in all_metrics]
    per_fold_ap = [m.get("average_precision", 0.0) for m in all_metrics]

    pooled_metrics["per_fold_f1"] = per_fold_f1
    pooled_metrics["per_fold_auc_roc"] = per_fold_auc
    pooled_metrics["per_fold_ap"] = per_fold_ap
    pooled_metrics["mean_fold_f1"] = float(np.mean(per_fold_f1))
    pooled_metrics["std_fold_f1"] = float(np.std(per_fold_f1))
    pooled_metrics["mean_fold_auc_roc"] = float(np.mean(per_fold_auc))
    pooled_metrics["mean_fold_ap"] = float(np.mean(per_fold_ap))

    # HPO 最佳 F1 摘要
    hpo_cb_f1s = [m.get("hpo_catboost_f1", 0.0) for m in all_metrics]
    hpo_lgbm_f1s = [m.get("hpo_lightgbm_f1", 0.0) for m in all_metrics]
    hpo_xgb_f1s = [m.get("hpo_xgboost_f1", 0.0) for m in all_metrics]
    pooled_metrics["hpo_summary"] = {
        "catboost_inner_f1": {
            "mean": float(np.mean(hpo_cb_f1s)),
            "per_fold": hpo_cb_f1s,
        },
        "lightgbm_inner_f1": {
            "mean": float(np.mean(hpo_lgbm_f1s)),
            "per_fold": hpo_lgbm_f1s,
        },
        "xgboost_inner_f1": {
            "mean": float(np.mean(hpo_xgb_f1s)),
            "per_fold": hpo_xgb_f1s,
        },
    }

    pooled_metrics["per_fold_details"] = all_metrics

    # 儲存彙總結果
    pooled.to_parquet(root / "nested_oof_predictions.parquet", index=False)
    save_json(pooled_metrics, root / "nested_oof_metrics.json")

    logger.info(
        f"\n=== 巢狀 CV 彙總結果 ===\n"
        f"  Folds: {pooled_metrics['n_folds']}\n"
        f"  Pooled F1: {pooled_metrics['pooled_f1']:.4f} "
        f"(threshold={pooled_metrics['pooled_threshold']:.2f})\n"
        f"  Mean fold F1: {pooled_metrics['mean_fold_f1']:.4f} "
        f"+/- {pooled_metrics['std_fold_f1']:.4f}\n"
        f"  Pooled Precision: {pooled_metrics['pooled_precision']:.4f}\n"
        f"  Pooled Recall: {pooled_metrics['pooled_recall']:.4f}\n"
        f"  Pooled AUC-ROC: {pooled_metrics['pooled_auc_roc']:.4f}\n"
        f"  Pooled AP: {pooled_metrics['pooled_average_precision']:.4f}"
    )

    return pooled_metrics


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="巢狀交叉驗證 + 超參數最佳化 (Nested CV with HPO)"
    )
    parser.add_argument(
        "--outer-fold", type=int, default=None,
        help="執行指定的外層 fold (0-4)。"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="依序執行所有 5 個外層 folds。"
    )
    parser.add_argument(
        "--aggregate", action="store_true",
        help="彙總所有已完成的 fold 結果。"
    )
    parser.add_argument(
        "--n-trials", type=int, default=30,
        help="每個模型的 Optuna HPO trials 數 (預設: 30)。"
    )
    parser.add_argument(
        "--inner-folds", type=int, default=3,
        help="內層 HPO 的 fold 數 (預設: 3)。"
    )
    parser.add_argument(
        "--seed", type=int, default=RANDOM_SEED,
        help=f"隨機種子 (預設: {RANDOM_SEED})。"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    if args.aggregate:
        # 僅彙總模式
        result = aggregate_nested_results()
        print(f"\n=== 巢狀 CV 彙總完成 ===")
        print(f"Pooled F1: {result['pooled_f1']:.4f}")
        print(f"Mean fold F1: {result['mean_fold_f1']:.4f} +/- {result['std_fold_f1']:.4f}")
        print(f"Pooled AUC-ROC: {result['pooled_auc_roc']:.4f}")
        print(f"Pooled AP: {result['pooled_average_precision']:.4f}")
        return

    if args.all:
        # 執行所有 5 個外層 folds
        all_fold_metrics: list[dict[str, Any]] = []
        for fold_k in range(5):
            logger.info(f"\n{'='*60}")
            logger.info(f"外層 fold {fold_k}/4")
            logger.info(f"{'='*60}")
            fold_result = run_outer_fold(
                outer_fold=fold_k,
                n_trials=args.n_trials,
                n_inner_folds=args.inner_folds,
                seed=args.seed,
            )
            all_fold_metrics.append(fold_result)

        # 自動彙總
        print(f"\n所有 folds 完成，開始彙總...")
        agg = aggregate_nested_results()
        print(f"\n=== 巢狀 CV 最終結果 ===")
        print(f"Pooled F1: {agg['pooled_f1']:.4f}")
        print(f"Mean fold F1: {agg['mean_fold_f1']:.4f} +/- {agg['std_fold_f1']:.4f}")
        print(f"Pooled AUC-ROC: {agg['pooled_auc_roc']:.4f}")
        print(f"Pooled AP: {agg['pooled_average_precision']:.4f}")
        return

    if args.outer_fold is not None:
        # 單一 fold 模式
        fold_result = run_outer_fold(
            outer_fold=args.outer_fold,
            n_trials=args.n_trials,
            n_inner_folds=args.inner_folds,
            seed=args.seed,
        )
        print(f"\n=== 外層 fold {args.outer_fold} 完成 ===")
        print(f"F1: {fold_result['best_f1']:.4f} (threshold={fold_result['best_threshold']:.2f})")
        print(f"Precision: {fold_result['precision']:.4f}")
        print(f"Recall: {fold_result['recall']:.4f}")
        print(f"AUC-ROC: {fold_result['auc_roc']:.4f}")
        print(f"AP: {fold_result['average_precision']:.4f}")
        print(f"耗時: {fold_result['elapsed_s']:.0f}s")
        return

    # 未指定模式時顯示用法
    parser.print_help()


if __name__ == "__main__":
    main()
