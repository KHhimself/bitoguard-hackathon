# BitoGuard E15 — AWS 部署指南

## 概覽

將 E15 AML 偵測管線部署到 AWS SageMaker，包含訓練和推論端點。

```
BitoPro API → upload_data.py → S3 (7 張 parquet 表)
                                  ↓
Docker Image → build_and_push.sh → ECR
                                      ↓
                              launch_training.py → SageMaker Training Job
                                                     ↓
                                              model.tar.gz (S3)
                                                     ↓
                                           deploy_endpoint.py → SageMaker Endpoint
                                                                   ↓
                                                            POST /invocations
```

## 前置條件

1. **AWS CLI** 已安裝並設定（`aws configure`）
2. **Docker** 已安裝並啟動
3. **Python 3.11+** 搭配 `boto3`、`httpx`、`pandas`、`pyarrow`
4. **SageMaker Execution Role**：需具備 S3、ECR、SageMaker 存取權限
5. **ECR 存取權限**：帳號需能建立/推送 repository

## 一鍵部署

```bash
# 完整流程：build → upload → train → deploy
./scripts/aws/deploy_all.sh <ACCOUNT_ID> [REGION] [BUCKET]

# 範例
./scripts/aws/deploy_all.sh 123456789012 ap-northeast-1 bitoguard-e15-data
```

## 分步執行

### Step 1: 建置 Docker Image → ECR

```bash
./scripts/aws/build_and_push.sh <ACCOUNT_ID> <REGION>
```

產出：`<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/bitoguard-e15-training:latest`

### Step 2: 下載資料 → S3

```bash
python scripts/aws/upload_data.py \
  --bucket bitoguard-e15-data \
  --region ap-northeast-1
```

從 BitoPro API 下載 7 張表（63,770 users、~70 萬筆交易），轉 parquet 上傳 S3。

| 表 | 筆數 | 說明 |
|----|------|------|
| user_info | 63,770 | 使用者基本資料 |
| twd_transfer | 195,601 | 台幣轉帳 |
| crypto_transfer | 239,958 | 加密貨幣轉帳 |
| usdt_twd_trading | 217,634 | USDT/TWD 交易 |
| usdt_swap | 53,841 | USDT 兌換 |
| train_label | 51,017 | 訓練標籤（正樣本 1,640，3.21%） |
| predict_label | 12,753 | 預測目標 user_id |

### Step 3: 啟動 SageMaker Training

```bash
python scripts/aws/launch_training.py \
  --account-id 123456789012 \
  --region ap-northeast-1 \
  --bucket bitoguard-e15-data \
  --instance-type ml.m5.xlarge
```

Training Job 執行 E15 完整管線：
1. 資料品質檢查
2. 表格特徵工程（~110 欄）
3. 圖特徵（~17 欄）
4. 異常偵測特徵（~29 欄）
5. 訓練 CatBoost×4 + XGBoost×2 + LR stacker + 校準器
6. OOF 驗證
7. 產出 submission CSV

產出：`model.tar.gz` 於 `s3://<bucket>/training-output/` 下。

### Step 4: 部署 SageMaker Endpoint

```bash
python scripts/aws/deploy_endpoint.py \
  --account-id 123456789012 \
  --region ap-northeast-1 \
  --model-data s3://bitoguard-e15-data/training-output/.../model.tar.gz
```

## SageMaker 目錄對應

```
S3 raw/*.parquet        → /opt/ml/input/data/raw/     (BITOGUARD_AWS_EVENT_RAW_DIR)
（訓練中產生）           → /opt/ml/work/clean/          (BITOGUARD_AWS_EVENT_CLEAN_DIR)
（訓練中產生）           → /opt/ml/work/artifacts/      (BITOGUARD_ARTIFACT_DIR)
Model output            → /opt/ml/model/               → model.tar.gz → S3
Submission CSV          → /opt/ml/output/data/
```

## Endpoint 推論

```bash
# 測試
aws sagemaker-runtime invoke-endpoint \
  --endpoint-name bitoguard-e15-endpoint \
  --content-type application/json \
  --body '{"instances": [{"user_id": "U001", "feature1": 0.5}]}' \
  --region ap-northeast-1 \
  output.json
```

**Endpoint 模式限制：**
- C&S（Correct & Smooth）不可用 → `base_c_s_probability = base_a_probability`
- Base B/C/D branches 不可用 → 機率設為 0
- 仍使用 stacker 21 meta features → calibrator → threshold ≥ 0.21

## Instance 類型與比賽帳號限制

| 用途 | Instance | Quota | 說明 |
|------|----------|-------|------|
| 訓練 | ml.m5.xlarge | 10 | 4 vCPU, 16GB RAM |
| 推論 | ml.c5.large | 8 | 2 vCPU, 4GB RAM |
| GPU | N/A | 0 | 比賽帳號不支援 GPU |

## 清理資源

Demo 完畢後記得清理，避免持續產生費用：

```bash
# 刪除 endpoint
aws sagemaker delete-endpoint \
  --endpoint-name bitoguard-e15-endpoint \
  --region ap-northeast-1

# 刪除 S3 資料
aws s3 rm s3://bitoguard-e15-data --recursive

# 刪除 ECR image
aws ecr delete-repository \
  --repository-name bitoguard-e15-training \
  --force --region ap-northeast-1
```

## 疑難排解

### 訓練失敗
```bash
# 查看 CloudWatch Logs
aws logs get-log-events \
  --log-group-name /aws/sagemaker/TrainingJobs \
  --log-stream-name <job-name>/algo-1 \
  --region ap-northeast-1
```

### DuckDB 鎖定錯誤
DuckDB 只允許單一寫入者。若訓練容器報 lock error，確認沒有其他 process 正在使用 .duckdb 檔案。

### xgboost ImportError
確認 `requirements.txt` 包含 `xgboost>=2.0`，且 Docker image 已重新建置。

### libgomp 錯誤
CatBoost 需要 OpenMP。確認 `Dockerfile.training` 有安裝 `libgomp1`。
