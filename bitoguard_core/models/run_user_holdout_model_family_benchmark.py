from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.model_selection import train_test_split

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from models.ablate_user_holdout import (
    _evaluate_probabilities,
    _fit_model_probabilities,
    _overlap_stats,
    _prepare_split,
    _summarize_sweep,
)
from models.common import feature_columns, training_dataset


DEFAULT_SEEDS = (42, 52)
DEFAULT_NEGATIVE_WEIGHTS = (1.0, 0.1, 0.05)
DEFAULT_MODEL_FAMILIES = ("lgbm", "xgboost", "catboost", "extratrees")


def _dataset_snapshot_path() -> Path:
    return ROOT_DIR / "artifacts" / "reports" / "user_holdout_dataset_snapshot.parquet"


def _report_path() -> Path:
    return ROOT_DIR / "artifacts" / "reports" / "user_holdout_model_family_report.json"


def ensure_dataset_snapshot() -> Path:
    path = _dataset_snapshot_path()
    if path.exists():
        return path
    dataset = training_dataset().sort_values("snapshot_date").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(path, index=False)
    return path


def _user_split_payloads(dataset: pd.DataFrame, seeds: tuple[int, ...]) -> list[dict[str, Any]]:
    user_labels = dataset.groupby("user_id", as_index=False)["hidden_suspicious_label"].max()
    payloads: list[dict[str, Any]] = []
    for seed in seeds:
        users_trainvalid, users_test = train_test_split(
            user_labels,
            test_size=0.15,
            stratify=user_labels["hidden_suspicious_label"],
            random_state=seed,
        )
        users_train, users_valid = train_test_split(
            users_trainvalid,
            test_size=0.17647058823529413,
            stratify=users_trainvalid["hidden_suspicious_label"],
            random_state=seed,
        )
        payloads.append({
            "seed": int(seed),
            "train_ids": sorted(users_train["user_id"].tolist()),
            "valid_ids": sorted(users_valid["user_id"].tolist()),
            "test_ids": sorted(users_test["user_id"].tolist()),
        })
    return payloads


def _run_worker(
    dataset_path: Path,
    split_payload: dict[str, Any],
    model_family: str,
    negative_weight: float,
    use_gpu_workers: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--dataset-path",
        str(dataset_path),
        "--split-json-path",
        str(_write_split_payload(split_payload)),
        "--family",
        model_family,
        "--negative-weight",
        str(negative_weight),
    ]
    env = os.environ.copy()
    env["BITOGUARD_USE_GPU"] = "1" if use_gpu_workers else "0"
    proc = subprocess.run(command, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker failed for seed={split_payload['seed']} family={model_family} "
            f"negative_weight={negative_weight}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def run_worker_once(
    dataset_path: Path,
    split_payload: dict[str, Any],
    model_family: str,
    negative_weight: float,
) -> dict[str, Any]:
    dataset = pd.read_parquet(dataset_path).sort_values("snapshot_date").reset_index(drop=True)
    train = dataset[dataset["user_id"].isin(split_payload["train_ids"])].reset_index(drop=True)
    valid = dataset[dataset["user_id"].isin(split_payload["valid_ids"])].reset_index(drop=True)
    test = dataset[dataset["user_id"].isin(split_payload["test_ids"])].reset_index(drop=True)
    features = feature_columns(dataset)
    split = _prepare_split(train, valid, test, features)
    valid_probabilities, test_probabilities, fit_seconds = _fit_model_probabilities(
        model_family=model_family,
        split=split,
        negative_weight=negative_weight,
    )
    return {
        "seed": int(split_payload["seed"]),
        "overlap": _overlap_stats(set(train["user_id"]), set(valid["user_id"]), set(test["user_id"])),
        **_evaluate_probabilities(
            model_family=model_family,
            split=split,
            negative_weight=negative_weight,
            valid_probabilities=valid_probabilities,
            test_probabilities=test_probabilities,
            fit_seconds=fit_seconds,
        ),
    }


def _write_split_payload(split_payload: dict[str, Any]) -> Path:
    seed = int(split_payload["seed"])
    path = ROOT_DIR / "artifacts" / "reports" / f"user_holdout_seed_{seed}_split.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_driver(use_gpu_workers: bool = False) -> dict[str, Any]:
    dataset_path = ensure_dataset_snapshot()
    dataset = pd.read_parquet(dataset_path)
    split_payloads = _user_split_payloads(dataset, DEFAULT_SEEDS)
    records: list[dict[str, Any]] = []

    for split_payload in split_payloads:
        for negative_weight in DEFAULT_NEGATIVE_WEIGHTS:
            for model_family in DEFAULT_MODEL_FAMILIES:
                result = _run_worker(
                    dataset_path=dataset_path,
                    split_payload=split_payload,
                    model_family=model_family,
                    negative_weight=negative_weight,
                    use_gpu_workers=use_gpu_workers,
                )
                records.append(result)
                print(json.dumps({
                    "seed": split_payload["seed"],
                    "negative_weight": negative_weight,
                    "model_family": model_family,
                    "test_average_precision": result["test_average_precision"],
                    "test_f1_at_selected_threshold": result["test_f1_at_selected_threshold"],
                    "top_5pct_f1": result["topk"]["top_5pct"]["f1"],
                    "top_valid_alert_rate_f1": result["topk"]["top_valid_alert_rate"]["f1"],
                }), flush=True)

                payload = {
                    "dataset_path": str(dataset_path),
                    "record_count": len(records),
                    "records": records,
                    "summary": _summarize_sweep(records),
                }
                report_path = _report_path()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = _summarize_sweep(records)
    report = {
        "dataset_path": str(dataset_path),
        "record_count": len(records),
        "records": records,
        "summary": summary,
        "best_configuration": summary[0] if summary else None,
    }
    report_path = _report_path()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--dataset-path")
    parser.add_argument("--split-json")
    parser.add_argument("--split-json-path")
    parser.add_argument("--family")
    parser.add_argument("--negative-weight", type=float)
    parser.add_argument("--use-gpu-workers", action="store_true")
    args = parser.parse_args()

    if args.worker:
        result = run_worker_once(
            dataset_path=Path(args.dataset_path),
            split_payload=json.loads(Path(args.split_json_path).read_text(encoding="utf-8")) if args.split_json_path else json.loads(args.split_json),
            model_family=str(args.family),
            negative_weight=float(args.negative_weight),
        )
        print(json.dumps(result, ensure_ascii=False))
        return

    report = run_driver(use_gpu_workers=args.use_gpu_workers)
    print(json.dumps({
        "report_path": str(_report_path()),
        "best_configuration": report["best_configuration"],
        "top_configurations": report["summary"][:10],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
