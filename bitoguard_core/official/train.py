from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import train_test_split

from official.anomaly import build_official_anomaly_features
from official.common import RANDOM_SEED, encode_frame, feature_output_path, load_official_paths, save_json, save_pickle
from official.features import build_official_features
from official.graph_features import build_official_graph_features
from official.rules import evaluate_official_rules


META_COLUMNS = {
    "user_id",
    "cohort",
    "snapshot_cutoff_at",
    "snapshot_cutoff_tag",
    "status",
    "needs_prediction",
    "in_train_label",
    "in_predict_label",
    "is_shadow_overlap",
}


def _load_dataset(cutoff_tag: str = "full") -> pd.DataFrame:
    feature_path = feature_output_path("official_user_features", cutoff_tag)
    graph_path = feature_output_path("official_graph_features", cutoff_tag)
    anomaly_path = feature_output_path("official_anomaly_features", cutoff_tag)
    if not feature_path.exists():
        build_official_features(cutoff_tag=cutoff_tag)
    if not graph_path.exists():
        build_official_graph_features(cutoff_tag=cutoff_tag)
    if not anomaly_path.exists():
        build_official_anomaly_features(cutoff_tag=cutoff_tag)
    dataset = pd.read_parquet(feature_path)
    dataset = dataset.merge(pd.read_parquet(graph_path), on=["user_id", "snapshot_cutoff_at", "snapshot_cutoff_tag"], how="left")
    dataset = dataset.merge(pd.read_parquet(anomaly_path), on=["user_id", "snapshot_cutoff_at", "snapshot_cutoff_tag"], how="left")
    dataset = dataset.merge(evaluate_official_rules(dataset), on="user_id", how="left")
    return dataset


def _split_train_valid_test(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    labels = frame["status"].astype(int)
    train_frame, temp_frame = train_test_split(
        frame,
        test_size=0.30,
        random_state=RANDOM_SEED,
        stratify=labels,
    )
    temp_labels = temp_frame["status"].astype(int)
    valid_frame, test_frame = train_test_split(
        temp_frame,
        test_size=0.50,
        random_state=RANDOM_SEED,
        stratify=temp_labels,
    )
    return train_frame.copy(), valid_frame.copy(), test_frame.copy()


def train_official_model() -> dict[str, str]:
    dataset = _load_dataset("full")
    supervised = dataset[dataset["cohort"] == "train_only"].copy()
    train_frame, valid_frame, test_frame = _split_train_valid_test(supervised)

    feature_columns = [column for column in dataset.columns if column not in META_COLUMNS]
    x_train, encoded_columns = encode_frame(train_frame, feature_columns)
    x_valid, _ = encode_frame(valid_frame, feature_columns, reference_columns=encoded_columns)
    y_train = train_frame["status"].astype(int)
    y_valid = valid_frame["status"].astype(int)

    positives = max(1, int(y_train.sum()))
    negatives = max(1, len(y_train) - positives)
    model = LGBMClassifier(
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=RANDOM_SEED,
        scale_pos_weight=negatives / positives,
    )
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        eval_metric="binary_logloss",
    )

    paths = load_official_paths()
    version = f"official_lgbm_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    model_path = paths.model_dir / f"{version}.pkl"
    meta_path = paths.model_dir / f"{version}.json"
    split_path = paths.feature_dir / "official_primary_split.parquet"
    split_frame = pd.concat(
        [
            train_frame.assign(split="train"),
            valid_frame.assign(split="valid"),
            test_frame.assign(split="test"),
        ],
        ignore_index=True,
    )[["user_id", "split", "status"]]
    split_frame.to_parquet(split_path, index=False)

    save_pickle(model, model_path)
    save_json(
        {
            "model_version": version,
            "feature_columns": feature_columns,
            "encoded_columns": encoded_columns,
            "split_path": str(split_path),
            "training_cohort": "train_only",
            "train_rows": int(len(train_frame)),
            "valid_rows": int(len(valid_frame)),
            "test_rows": int(len(test_frame)),
            "random_seed": RANDOM_SEED,
        },
        meta_path,
    )
    return {"model_version": version, "model_path": str(model_path), "meta_path": str(meta_path)}


def main() -> None:
    print(train_official_model())


if __name__ == "__main__":
    main()
