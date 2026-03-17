"""Evaluate stacker with F1 / precision / recall at multiple thresholds.

NOTE: This script uses the **final** branch models (trained on all training data),
so predictions on the training set are in-sample (optimistically biased).
AUC and PR-AUC from cv_results_*.json are the authoritative OOF estimates.
Use this script for threshold selection and per-class breakdown — not for
reporting generalization performance.

Usage (from bitoguard_core/):
    PYTHONPATH=. python models/eval_oof.py
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import (
    f1_score, precision_score, recall_score,
    precision_recall_curve, roc_auc_score, average_precision_score,
    confusion_matrix, classification_report,
)

from config import load_settings
from models.common import (
    NON_FEATURE_COLUMNS, forward_date_splits, model_dir,
)
from models.train_catboost import load_v2_training_dataset, CAT_FEATURE_NAMES


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


def _load_latest(prefix: str, ext: str = "joblib"):
    import joblib, glob
    mdir = model_dir()
    candidates = sorted(
        Path(mdir).glob(f"{prefix}_*.{ext}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No {prefix}_*.{ext} in {mdir}")
    path = candidates[0]
    print(f"  Loading {path.name}")
    return joblib.load(path)


def main():
    settings = load_settings()

    # ── Load dataset ──────────────────────────────────────────────────────────
    print("Loading training dataset …")
    dataset = load_v2_training_dataset()
    feature_cols = [c for c in dataset.columns
                    if c not in NON_FEATURE_COLUMNS and c != "hidden_suspicious_label"]
    cat_indices  = [i for i, c in enumerate(feature_cols) if c in CAT_FEATURE_NAMES]

    date_splits = forward_date_splits(dataset["snapshot_date"])
    train_dates = set(date_splits["train"])
    df = dataset[dataset["snapshot_date"].dt.date.isin(train_dates)].copy()
    df = df.reset_index(drop=True)

    x_df = df[feature_cols].fillna(0).reset_index(drop=True)
    y    = df["hidden_suspicious_label"].values

    # Numeric-only matrix for XGB/ET/RF
    x_np = x_df.copy()
    for col in x_np.select_dtypes(include=["object", "category"]).columns:
        x_np[col] = pd.Categorical(x_np[col]).codes.astype("float32")
    x_np = x_np.values.astype("float32")

    prevalence = y.mean()
    print(f"Dataset: {len(y):,} samples, {int(y.sum()):,} positives ({prevalence:.2%} prevalence)\n")

    # ── Load final branch models ───────────────────────────────────────────────
    print("Loading branch models …")
    cb   = _load_latest("cb")
    lgbm = _load_latest("lgbm_v2")
    xgb  = _load_latest("xgb")
    et   = _load_latest("et")
    rf   = _load_latest("rf")
    stacker = _load_latest("stacker")

    # ── Branch predictions ─────────────────────────────────────────────────────
    print("\nRunning branch predictions (in-sample) …")
    p_cb   = cb.predict_proba(x_df)[:, 1]
    p_lgbm = lgbm.predict_proba(x_df)[:, 1]
    p_xgb  = xgb.predict_proba(x_np)[:, 1]
    p_et   = et.predict_proba(x_np)[:, 1]
    p_rf   = rf.predict_proba(x_np)[:, 1]

    # ── Stacker (meta-learner) predictions ────────────────────────────────────
    meta_features = np.column_stack([
        _logit(p_cb), _logit(p_lgbm), _logit(p_xgb),
        _logit(p_et), _logit(p_rf),
    ])
    p_stacker = stacker.predict_proba(meta_features)[:, 1]

    # ── AUC / PR-AUC (in-sample — compare with OOF from cv_results) ───────────
    print("\n⚠  IN-SAMPLE metrics (optimistic). Compare PR-AUC with OOF cv_results.")
    print(f"   Stacker AUC    = {roc_auc_score(y, p_stacker):.4f}")
    print(f"   Stacker PR-AUC = {average_precision_score(y, p_stacker):.4f}")
    print(f"   Score range    [{p_stacker.min():.4f}, {p_stacker.max():.4f}]")

    # ── F1 / Precision / Recall sweep ─────────────────────────────────────────
    thresholds = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]

    print("\n" + "─" * 70)
    print(f"{'Threshold':>10} {'Precision':>10} {'Recall':>8} {'F1':>8} {'Alerts':>8} {'% flagged':>10}")
    print("─" * 70)
    for t in thresholds:
        pred = (p_stacker >= t).astype(int)
        p  = precision_score(y, pred, zero_division=0)
        r  = recall_score(y, pred, zero_division=0)
        f1 = f1_score(y, pred, zero_division=0)
        n_flagged = pred.sum()
        print(f"{t:>10.2f} {p:>10.4f} {r:>8.4f} {f1:>8.4f} {n_flagged:>8,} {n_flagged/len(y)*100:>9.1f}%")
    print("─" * 70)

    # ── Optimal-F1 threshold ───────────────────────────────────────────────────
    prec_curve, rec_curve, thr_curve = precision_recall_curve(y, p_stacker)
    # thr_curve has one fewer element than prec/rec
    f1_curve = np.where(
        (prec_curve[:-1] + rec_curve[:-1]) > 0,
        2 * prec_curve[:-1] * rec_curve[:-1] / (prec_curve[:-1] + rec_curve[:-1]),
        0,
    )
    best_idx = int(np.argmax(f1_curve))
    best_thr = float(thr_curve[best_idx])
    best_f1  = float(f1_curve[best_idx])
    best_p   = float(prec_curve[best_idx])
    best_r   = float(rec_curve[best_idx])

    print(f"\nOptimal-F1 threshold : {best_thr:.4f}")
    print(f"  Precision          : {best_p:.4f}")
    print(f"  Recall             : {best_r:.4f}")
    print(f"  F1                 : {best_f1:.4f}")
    flagged = (p_stacker >= best_thr).sum()
    print(f"  Flagged            : {flagged:,} / {len(y):,} ({flagged/len(y)*100:.1f}%)")

    # Confusion matrix at optimal threshold
    pred_opt = (p_stacker >= best_thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred_opt).ravel()
    print(f"\nConfusion matrix @ threshold {best_thr:.4f}:")
    print(f"  TP={tp:,}  FP={fp:,}  FN={fn:,}  TN={tn:,}")
    print(f"  Lift = {best_p / prevalence:.1f}x  (precision / base rate)")

    # ── Per-branch F1 @ optimal stacker threshold ──────────────────────────────
    print("\nPer-branch metrics @ stacker optimal threshold:")
    print(f"{'Branch':>15} {'AUC':>8} {'PR-AUC':>8} {'F1@opt':>8}")
    print("─" * 45)
    for name, scores in [
        ("CatBoost",    p_cb),
        ("LightGBM",    p_lgbm),
        ("XGBoost",     p_xgb),
        ("ExtraTrees",  p_et),
        ("RandomForest",p_rf),
    ]:
        auc = roc_auc_score(y, scores)
        ap  = average_precision_score(y, scores)
        # F1 at the branch's own optimal threshold
        prec_b, rec_b, thr_b = precision_recall_curve(y, scores)
        f1_b = np.where(
            (prec_b[:-1] + rec_b[:-1]) > 0,
            2 * prec_b[:-1] * rec_b[:-1] / (prec_b[:-1] + rec_b[:-1]),
            0,
        )
        best_f1_b = float(np.max(f1_b))
        print(f"{name:>15} {auc:>8.4f} {ap:>8.4f} {best_f1_b:>8.4f}")

    # ── Save results ───────────────────────────────────────────────────────────
    out = {
        "note": "in-sample metrics (final models trained on all training data — optimistically biased)",
        "n_samples": int(len(y)),
        "n_positives": int(y.sum()),
        "prevalence": float(prevalence),
        "stacker_auc_insample": float(roc_auc_score(y, p_stacker)),
        "stacker_pr_auc_insample": float(average_precision_score(y, p_stacker)),
        "oof_auc_from_cv": 0.8578,     # from cv_results JSON (authoritative)
        "oof_pr_auc_from_cv": 0.2161,  # from cv_results JSON (authoritative)
        "optimal_threshold": best_thr,
        "optimal_f1": best_f1,
        "optimal_precision": best_p,
        "optimal_recall": best_r,
        "threshold_sweep": [
            {
                "threshold": t,
                "precision": float(precision_score(y, (p_stacker >= t).astype(int), zero_division=0)),
                "recall":    float(recall_score(y,    (p_stacker >= t).astype(int), zero_division=0)),
                "f1":        float(f1_score(y,        (p_stacker >= t).astype(int), zero_division=0)),
                "n_flagged": int((p_stacker >= t).sum()),
            }
            for t in thresholds
        ],
    }
    out_path = Path(settings.artifact_dir) / "models" / "eval_insample.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nResults saved → {out_path}")


if __name__ == "__main__":
    main()
