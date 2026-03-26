from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from official.common import OFFICIAL_TABLES, PRIMARY_KEY_COLUMNS, feature_output_path, feature_report_path, load_clean_table, load_raw_table, save_json


COHORT_ORDER = ("train_only", "shadow_overlap", "predict_only", "unlabeled_only")
SCALING_CHECKS = {
    "twd_transfer": [("ori_samount_raw", "amount_twd")],
    "crypto_transfer": [("ori_samount_raw", "amount_asset"), ("twd_srate_raw", "twd_rate")],
    "usdt_swap": [("twd_samount_raw", "twd_amount"), ("currency_samount_raw", "currency_amount")],
    "usdt_twd_trading": [("trade_samount_raw", "trade_amount_usdt"), ("twd_srate_raw", "twd_rate")],
}


@dataclass(frozen=True)
class CohortCounts:
    train_only: int
    shadow_overlap: int
    predict_only: int
    unlabeled_only: int
    all_users: int


def build_official_cohorts(write_outputs: bool = True) -> pd.DataFrame:
    user_index = load_clean_table("user_index").copy()
    user_index["user_id"] = pd.to_numeric(user_index["user_id"], errors="coerce").astype("Int64")
    user_index["in_train_label"] = user_index["status"].notna()
    user_index["in_predict_label"] = user_index["needs_prediction"].eq(True)
    user_index["is_shadow_overlap"] = user_index["in_train_label"] & user_index["in_predict_label"]
    user_index["cohort"] = "unlabeled_only"
    user_index.loc[user_index["in_train_label"] & ~user_index["in_predict_label"], "cohort"] = "train_only"
    user_index.loc[user_index["is_shadow_overlap"], "cohort"] = "shadow_overlap"
    user_index.loc[~user_index["in_train_label"] & user_index["in_predict_label"], "cohort"] = "predict_only"
    user_index["cohort"] = pd.Categorical(user_index["cohort"], categories=COHORT_ORDER, ordered=True)
    user_index = user_index.sort_values(["cohort", "user_id"]).reset_index(drop=True)

    if write_outputs:
        user_index.to_parquet(feature_output_path("cohorts"), index=False)

    return user_index


def cohort_counts(frame: pd.DataFrame) -> CohortCounts:
    counts = frame["cohort"].value_counts().to_dict()
    return CohortCounts(
        train_only=int(counts.get("train_only", 0)),
        shadow_overlap=int(counts.get("shadow_overlap", 0)),
        predict_only=int(counts.get("predict_only", 0)),
        unlabeled_only=int(counts.get("unlabeled_only", 0)),
        all_users=int(len(frame)),
    )


def _primary_key_checks() -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for table_name in OFFICIAL_TABLES:
        frame = load_clean_table(table_name)
        primary_key = PRIMARY_KEY_COLUMNS[table_name]
        duplicate_count = int(frame.duplicated(subset=[primary_key]).sum())
        checks[table_name] = {
            "rows": int(len(frame)),
            "primary_key": primary_key,
            "duplicate_primary_keys": duplicate_count,
        }
    return checks


def _user_integrity_checks() -> dict[str, dict[str, int]]:
    users = set(load_clean_table("user_info")["user_id"].tolist())
    checks: dict[str, dict[str, int]] = {}
    for table_name in ("train_label", "predict_label", "twd_transfer", "crypto_transfer", "usdt_swap", "usdt_twd_trading"):
        frame = load_clean_table(table_name)
        orphan_rows = int((~frame["user_id"].isin(users)).sum())
        checks[table_name] = {"orphan_user_rows": orphan_rows}
    return checks


def _null_summary() -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for table_name in OFFICIAL_TABLES:
        frame = load_clean_table(table_name)
        summary[table_name] = {
            column: round(float(frame[column].isna().mean()), 6)
            for column in frame.columns
            if frame[column].isna().any()
        }
    return summary


def _scaling_checks() -> dict[str, dict[str, float]]:
    report: dict[str, dict[str, float]] = {}
    for table_name, mappings in SCALING_CHECKS.items():
        clean = load_clean_table(table_name)
        table_report: dict[str, float] = {}
        for raw_column, clean_column in mappings:
            expected = clean[raw_column] * 1e-8
            delta = (expected - clean[clean_column]).abs().fillna(0.0)
            table_report[f"{clean_column}_max_abs_error"] = float(delta.max())
        report[table_name] = table_report
    return report


def build_official_data_contract_report() -> dict[str, Any]:
    cohorts = build_official_cohorts(write_outputs=True)
    counts = cohort_counts(cohorts)
    report = {
        "cohort_counts": asdict(counts),
        "primary_key_checks": _primary_key_checks(),
        "user_integrity_checks": _user_integrity_checks(),
        "scaling_checks": _scaling_checks(),
        "null_summary": _null_summary(),
    }
    save_json(report, feature_report_path("official_data_contract_report.json"))
    return report


def main() -> None:
    build_official_data_contract_report()


if __name__ == "__main__":
    main()
