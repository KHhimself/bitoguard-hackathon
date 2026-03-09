from __future__ import annotations

import json

import pandas as pd

from official.common import encode_frame, load_clean_table, load_official_paths, load_pickle
from official.train import _load_dataset


def _load_latest() -> tuple[object, dict]:
    paths = load_official_paths()
    model_files = sorted(paths.model_dir.glob("official_lgbm_*.pkl"))
    if not model_files:
        raise FileNotFoundError("No official_lgbm model found")
    model_path = model_files[-1]
    meta = json.loads(model_path.with_suffix(".json").read_text(encoding="utf-8"))
    return load_pickle(model_path), meta


def score_official_predict() -> pd.DataFrame:
    dataset = _load_dataset("full")
    model, meta = _load_latest()
    predict_users = set(load_parquet_predict_ids())
    scoring = dataset[dataset["user_id"].isin(predict_users)].copy()
    x_score, _ = encode_frame(scoring, meta["feature_columns"], reference_columns=meta["encoded_columns"])
    scoring["model_probability"] = model.predict_proba(x_score)[:, 1]
    scoring["risk_score"] = (
        0.75 * scoring["model_probability"]
        + 0.15 * scoring["anomaly_score"]
        + 0.10 * scoring["rule_score"]
    ) * 100.0
    scoring["risk_rank"] = scoring["risk_score"].rank(method="first", ascending=False).astype(int)
    scoring["risk_level"] = pd.cut(
        scoring["risk_score"],
        bins=[-1, 35, 60, 80, 100],
        labels=["low", "medium", "high", "critical"],
    ).astype(str)
    output = scoring[[
        "user_id",
        "risk_score",
        "model_probability",
        "anomaly_score",
        "risk_rank",
        "risk_level",
        "top_reason_codes",
        "is_shadow_overlap",
    ]].sort_values("risk_rank")
    paths = load_official_paths()
    output.to_parquet(paths.prediction_dir / "official_predict_scores.parquet", index=False)
    output.to_csv(paths.prediction_dir / "official_predict_scores.csv", index=False)
    return output


def load_parquet_predict_ids() -> list[int]:
    predict = load_clean_table("predict_label")
    return predict["user_id"].astype(int).tolist()


def main() -> None:
    print(score_official_predict().head())


if __name__ == "__main__":
    main()
