"""Standalone pipeline runner script for the official train+validate+score pipeline.
Written to disk to avoid tee/pipe buffering issues when running long subprocesses.
"""
from __future__ import annotations
import json
import sys
import time

import numpy as np

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from official.train import train_official_model
from official.validate import validate_official_model
from official.score import score_official_predict

print("=== TRAINING ===", flush=True)
print("CatBoost: CPU mode (Focal+AUC not GPU-supported in catboost 1.2.10)", flush=True)
print("GraphSAGE: GPU mode (PyTorch)", flush=True)
t0 = time.time()
result = train_official_model()
train_elapsed = time.time() - t0
print(f"Training completed in {train_elapsed:.1f}s ({train_elapsed/60:.1f}min)", flush=True)

skip = {"base_a_feature_columns", "base_b_feature_columns", "oof_predictions", "fold_training_meta"}
print(json.dumps({k: result[k] for k in result if k not in skip}, indent=2, default=str), flush=True)

if "oof_predictions" in result:
    oof = result["oof_predictions"]
    print("OOF columns:", list(oof.columns), flush=True)
    for col in ["base_a_probability", "base_b_probability", "base_c_probability"]:
        if col in oof.columns:
            arr = oof[col].dropna().values.astype(float)
            pct_at_1 = float(np.mean(arr >= 0.999))
            print(
                f"  {col}: n={len(arr)}, mean={arr.mean():.4f}, "
                f"max={arr.max():.4f}, pct_at_1={pct_at_1:.4f}",
                flush=True,
            )
        else:
            print(f"  {col}: NOT in OOF columns", flush=True)

print("", flush=True)
print("=== VALIDATING ===", flush=True)
t1 = time.time()
val = validate_official_model()
val_elapsed = time.time() - t1
print(f"Validation completed in {val_elapsed:.1f}s", flush=True)
print(json.dumps(val, indent=2, default=str), flush=True)

print("", flush=True)
print("=== SCORING ===", flush=True)
t2 = time.time()
scores = score_official_predict()
score_elapsed = time.time() - t2
print(f"Scoring completed in {score_elapsed:.1f}s", flush=True)
print(f"Scored {len(scores)} users", flush=True)
if "stacked_score" in scores.columns:
    print(scores[["stacked_score"]].describe().to_string(), flush=True)
else:
    print("Score columns:", list(scores.columns)[:10], flush=True)
    print(scores.describe().to_string(), flush=True)

print("", flush=True)
print("=== DONE ===", flush=True)
