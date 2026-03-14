from __future__ import annotations

from datetime import datetime, timezone

from lightgbm import LGBMClassifier

from models.common import encode_features, feature_columns, forward_date_splits, model_dir, save_json, save_lgbm, training_dataset


def train_model() -> dict:
    dataset = training_dataset().sort_values("snapshot_date").reset_index(drop=True)
    feature_cols = feature_columns(dataset)
    date_splits = forward_date_splits(dataset["snapshot_date"])
    train_dates = set(date_splits["train"])
    valid_dates = set(date_splits["valid"])
    holdout_dates = set(date_splits["holdout"])

    train_frame = dataset[dataset["snapshot_date"].dt.date.isin(train_dates)].copy()
    valid_frame = dataset[dataset["snapshot_date"].dt.date.isin(valid_dates)].copy()
    holdout_frame = dataset[dataset["snapshot_date"].dt.date.isin(holdout_dates)].copy()

    x_train, encoded_columns = encode_features(train_frame, feature_cols)
    x_valid, _ = encode_features(valid_frame, feature_cols, reference_columns=encoded_columns)
    x_holdout, _ = encode_features(holdout_frame, feature_cols, reference_columns=encoded_columns)
    y_train = train_frame["hidden_suspicious_label"]
    y_valid = valid_frame["hidden_suspicious_label"]

    positives = max(1, int(y_train.sum()))
    negatives = max(1, len(y_train) - positives)
    model = LGBMClassifier(
        n_estimators=250,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        scale_pos_weight=negatives / positives,
    )
    eval_set = [(x_valid, y_valid)] if not valid_frame.empty else [(x_train, y_train)]
    model.fit(
        x_train,
        y_train,
        eval_set=eval_set,
        eval_metric="binary_logloss",
        callbacks=[],
    )

    # ── Feature importance (gain-based) ──────────────────────────────────────
    try:
        gain_importance = model.booster_.feature_importance(importance_type="gain")
        total_gain = max(1.0, float(gain_importance.sum()))
        feature_importance = {
            col: round(float(imp) / total_gain, 6)
            for col, imp in sorted(
                zip(encoded_columns, gain_importance.tolist()),
                key=lambda x: -x[1],
            )
            if float(imp) > 0
        }
    except Exception:
        feature_importance = {}

    version = f"lgbm_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    model_path = model_dir() / f"{version}.lgbm"
    meta_path = model_dir() / f"{version}.json"
    save_lgbm(model, model_path)
    save_json(
        {
            "model_version": version,
            "feature_columns": feature_cols,
            "encoded_columns": encoded_columns,
            "train_dates": sorted(str(d) for d in train_dates),
            "valid_dates": sorted(str(d) for d in valid_dates),
            "holdout_dates": sorted(str(d) for d in holdout_dates),
            "holdout_rows": len(x_holdout),
            "feature_importance": feature_importance,
        },
        meta_path,
    )
    return {"model_version": version, "model_path": str(model_path), "meta_path": str(meta_path)}


if __name__ == "__main__":
    print(train_model())
