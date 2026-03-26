from __future__ import annotations

import sys
import time

from official.anomaly import build_official_anomaly_features
from official.cohorts import build_official_data_contract_report
from official.features import build_official_features
from official.graph_features import build_official_graph_features
from official.score import score_official_predict
from official.train import train_official_model
from official.validate import validate_official_model


def _log(msg: str) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[pipeline {ts}] {msg}", flush=True)


def run_official_pipeline() -> dict[str, object]:
    t0 = time.time()

    _log("Step 1/7: build_official_data_contract_report() ...")
    build_official_data_contract_report()
    _log(f"  完成 ({time.time()-t0:.0f}s)")

    t1 = time.time()
    _log("Step 2/7: build_official_features() — 表格特徵 ~110 cols ...")
    build_official_features()
    _log(f"  完成 ({time.time()-t1:.0f}s)")

    t2 = time.time()
    _log("Step 3/7: build_official_graph_features() — 圖特徵 ~17 cols ...")
    build_official_graph_features()
    _log(f"  完成 ({time.time()-t2:.0f}s)")

    t3 = time.time()
    _log("Step 4/7: build_official_anomaly_features() — IsolationForest + LOF + OCSVM ...")
    build_official_anomaly_features()
    _log(f"  完成 ({time.time()-t3:.0f}s)")

    t4 = time.time()
    _log("Step 5/7: train_official_model() — CatBoost×4 + XGB×2 + LGB×3 + stacker ...")
    train_meta = train_official_model()
    _log(f"  完成 ({time.time()-t4:.0f}s)")

    t5 = time.time()
    _log("Step 6/7: validate_official_model() — calibration + threshold + honest eval ...")
    validation = validate_official_model()
    _log(f"  完成 ({time.time()-t5:.0f}s)")

    t6 = time.time()
    _log("Step 7/7: score_official_predict() — 產出 submission CSV ...")
    predictions = score_official_predict()
    _log(f"  完成 ({time.time()-t6:.0f}s)")

    _log(f"Pipeline 全部完成！總耗時 {time.time()-t0:.0f}s")

    return {
        "train_meta": train_meta,
        "validation_report_path": "bitoguard_core/artifacts/reports/official_validation_report.json",
        "prediction_rows": int(len(predictions)),
        "selected_threshold": validation["selected_threshold"],
    }


def main() -> None:
    print(run_official_pipeline())


if __name__ == "__main__":
    main()
