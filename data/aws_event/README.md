# AWS Event Dataset

這個目錄專門放主辦方 `aws-event-api` 的官方資料，不再依賴本地 pseudo data。

目錄結構：

- `raw/`: 直接從官方 API 抓回來的原始 parquet 與 manifest
- `clean/`: 清洗後、可直接做特徵工程的 parquet 與 manifest

抓取原始資料：

```bash
./bitoguard_core/.venv/bin/python scripts/fetch_aws_event_data.py
```

清洗原始資料：

```bash
./bitoguard_core/.venv/bin/python scripts/clean_aws_event_data.py
```

常用參數：

```bash
./bitoguard_core/.venv/bin/python scripts/fetch_aws_event_data.py --page-size 20000 --overwrite
./bitoguard_core/.venv/bin/python scripts/clean_aws_event_data.py --overwrite
```

說明：

- 原始資料預設會寫到 `data/aws_event/raw`
- 清洗後資料預設會寫到 `data/aws_event/clean`
- 金額欄位會依主辦方欄位文件轉成真實值，原始縮放欄位會保留為 `*_raw`
- 目前 repo 內可直接使用 `bitoguard_core/.venv`；若你改用別的 Python 環境，需自行安裝 `pandas / pyarrow / httpx`
