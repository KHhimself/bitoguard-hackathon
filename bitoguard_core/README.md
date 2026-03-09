# BitoGuard Core

`bitoguard_core` 是 BitoGuard hackathon demo 的內部產品層，負責：

- 從 `bitoguard_mock_api` 同步資料進 DuckDB
- 建 canonical tables、graph edges、feature snapshots
- 訓練 LightGBM 與 Isolation Forest
- 產出 risk score、alerts、cases、risk diagnosis
- 提供 internal FastAPI，供 Next.js 前端讀取

## 安裝

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## 核心流程

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
. .venv/bin/activate

PYTHONPATH=. python pipeline/sync.py --full
PYTHONPATH=. python features/graph_features.py
PYTHONPATH=. python features/build_features.py
PYTHONPATH=. python models/train.py
PYTHONPATH=. python models/anomaly.py
PYTHONPATH=. python models/score.py
PYTHONPATH=. python models/validate.py
```

## 官方 aws-event 流程

官方資料版直接讀取 `../data/aws_event/clean`，不依賴 pseudo data，也不會改動既有 demo pipeline。

一鍵執行：

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
. .venv/bin/activate
PYTHONPATH=. python -m official.pipeline
```

分步執行：

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
. .venv/bin/activate

PYTHONPATH=. python -m official.cohorts
PYTHONPATH=. python -m official.features
PYTHONPATH=. python -m official.graph_features
PYTHONPATH=. python -m official.anomaly
PYTHONPATH=. python -m official.train
PYTHONPATH=. python -m official.validate
PYTHONPATH=. python -m official.score
```

主要輸出：

- `artifacts/models/official_lgbm_*.pkl|json`
- `artifacts/models/official_iforest_*.pkl|json`
- `artifacts/reports/official_data_contract_report.json`
- `artifacts/reports/official_validation_report.json`
- `artifacts/reports/official_shadow_report.json`
- `artifacts/predictions/official_predict_scores.parquet`
- `artifacts/predictions/official_predict_scores.csv`

若要用脫離 VS Code / 終端介面的方式重跑官方版 full pipeline：

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle
./scripts/restart_official_pipeline_tmux.sh
```

監看方式：

```bash
tmux attach -t bitoguard_official_pipeline
tmux capture-pane -pt bitoguard_official_pipeline | tail -n 100
tail -f bitoguard_core/artifacts/logs/official_pipeline.log
```

## Internal API

```bash
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
. .venv/bin/activate
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```
