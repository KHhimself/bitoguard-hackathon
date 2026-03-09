from __future__ import annotations

from official.anomaly import build_official_anomaly_features
from official.cohorts import build_official_data_contract_report
from official.features import build_official_features
from official.graph_features import build_official_graph_features
from official.score import score_official_predict
from official.train import train_official_model
from official.validate import validate_official_model


def run_official_pipeline() -> dict[str, object]:
    build_official_data_contract_report()
    build_official_features()
    build_official_graph_features()
    build_official_anomaly_features()
    train_meta = train_official_model()
    validation = validate_official_model()
    predictions = score_official_predict()
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
