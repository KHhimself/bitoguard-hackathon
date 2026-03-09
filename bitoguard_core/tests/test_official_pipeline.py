from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from official.cohorts import build_official_cohorts, build_official_data_contract_report
from official.pipeline import run_official_pipeline


RAW_TABLES = (
    "user_info",
    "train_label",
    "predict_label",
    "twd_transfer",
    "crypto_transfer",
    "usdt_swap",
    "usdt_twd_trading",
)
EVENT_TABLES = ("twd_transfer", "crypto_transfer", "usdt_swap", "usdt_twd_trading")


def _sample_users() -> dict[str, set[int]]:
    user_index = pd.read_parquet(Path(__file__).resolve().parents[2] / "data" / "aws_event" / "clean" / "user_index.parquet")
    train_only = user_index[user_index["status"].notna() & ~user_index["needs_prediction"]]
    train_positive = train_only[train_only["status"] == 1]["user_id"].astype(int).head(24)
    train_negative = train_only[train_only["status"] == 0]["user_id"].astype(int).head(96)
    shadow_overlap = user_index[user_index["status"].notna() & user_index["needs_prediction"]]["user_id"].astype(int).head(32)
    predict_only = user_index[user_index["status"].isna() & user_index["needs_prediction"]]["user_id"].astype(int).head(16)
    unlabeled_only = user_index[user_index["status"].isna() & ~user_index["needs_prediction"]]["user_id"].astype(int).head(16)
    return {
        "train_only": set(pd.concat([train_positive, train_negative]).tolist()),
        "shadow_overlap": set(shadow_overlap.tolist()),
        "predict_only": set(predict_only.tolist()),
        "unlabeled_only": set(unlabeled_only.tolist()),
    }


def _prepare_official_subset(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    source_root = Path(__file__).resolve().parents[2]
    raw_source = source_root / "data" / "aws_event" / "raw"
    clean_source = source_root / "data" / "aws_event" / "clean"
    raw_target = tmp_path / "raw"
    clean_target = tmp_path / "clean"
    raw_target.mkdir()
    clean_target.mkdir()

    cohorts = _sample_users()
    selected_users = set().union(*cohorts.values())
    for table_name in RAW_TABLES:
        raw_frame = pd.read_parquet(raw_source / f"{table_name}.parquet")
        clean_frame = pd.read_parquet(clean_source / f"{table_name}.parquet")
        if "user_id" in raw_frame.columns:
            raw_frame = raw_frame[raw_frame["user_id"].astype(int).isin(selected_users)].copy()
        if "user_id" in clean_frame.columns:
            clean_frame = clean_frame[clean_frame["user_id"].astype(int).isin(selected_users)].copy()
        raw_frame.to_parquet(raw_target / f"{table_name}.parquet", index=False)
        clean_frame.to_parquet(clean_target / f"{table_name}.parquet", index=False)

    clean_user_index = pd.read_parquet(clean_source / "user_index.parquet")
    clean_user_index = clean_user_index[clean_user_index["user_id"].astype(int).isin(selected_users)].copy()
    clean_user_index.to_parquet(clean_target / "user_index.parquet", index=False)

    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setenv("BITOGUARD_AWS_EVENT_RAW_DIR", str(raw_target))
    monkeypatch.setenv("BITOGUARD_AWS_EVENT_CLEAN_DIR", str(clean_target))
    monkeypatch.setenv("BITOGUARD_ARTIFACT_DIR", str(artifact_dir))
    return clean_target, artifact_dir


def test_official_data_contract_and_cohorts(tmp_path: Path, monkeypatch) -> None:
    clean_target, artifact_dir = _prepare_official_subset(tmp_path, monkeypatch)
    cohorts = build_official_cohorts()
    counts = cohorts["cohort"].value_counts().to_dict()
    assert counts["train_only"] == 120
    assert counts["shadow_overlap"] == 32
    assert counts["predict_only"] == 16
    assert counts["unlabeled_only"] == 16

    report = build_official_data_contract_report()
    assert report["cohort_counts"]["all_users"] == 184
    assert report["primary_key_checks"]["user_info"]["duplicate_primary_keys"] == 0
    assert report["user_integrity_checks"]["crypto_transfer"]["orphan_user_rows"] == 0
    assert (artifact_dir / "reports" / "official_data_contract_report.json").exists()
    assert (artifact_dir / "official_features" / "cohorts_full.parquet").exists()
    assert len(pd.read_parquet(clean_target / "predict_label.parquet")) == 48


def test_official_pipeline_end_to_end(tmp_path: Path, monkeypatch) -> None:
    clean_target, artifact_dir = _prepare_official_subset(tmp_path, monkeypatch)
    result = run_official_pipeline()

    validation_path = artifact_dir / "reports" / "official_validation_report.json"
    shadow_path = artifact_dir / "reports" / "official_shadow_report.json"
    prediction_path = artifact_dir / "predictions" / "official_predict_scores.parquet"
    split_path = artifact_dir / "official_features" / "official_primary_split.parquet"
    anomaly_meta_path = artifact_dir / "models" / sorted(p.name for p in (artifact_dir / "models").glob("official_iforest_*.json"))[-1]

    assert result["prediction_rows"] == len(pd.read_parquet(clean_target / "predict_label.parquet"))
    assert validation_path.exists()
    assert shadow_path.exists()
    assert prediction_path.exists()
    assert split_path.exists()

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert "threshold_sensitivity" in validation
    assert "temporal_stress_test" in validation
    assert validation["confusion_matrix"]["tp"] >= 0

    splits = pd.read_parquet(split_path)
    shadow_users = set(build_official_cohorts().query("cohort == 'shadow_overlap'")["user_id"].astype(int).tolist())
    assert shadow_users.isdisjoint(set(splits["user_id"].astype(int).tolist()))

    predictions = pd.read_parquet(prediction_path)
    assert len(predictions) == len(pd.read_parquet(clean_target / "predict_label.parquet"))
    assert predictions["is_shadow_overlap"].sum() == 32
    assert {"user_id", "risk_score", "model_probability", "anomaly_score", "risk_rank", "risk_level", "top_reason_codes", "is_shadow_overlap"} <= set(predictions.columns)

    anomaly_meta = json.loads((artifact_dir / "models" / anomaly_meta_path).read_text(encoding="utf-8"))
    assert anomaly_meta["fit_row_count"] == 152
