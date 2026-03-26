#!/usr/bin/env python3
"""
從 BitoPro API 下載 7 張表，轉成 parquet，上傳到 S3。

用法：
  python scripts/aws/upload_data.py --bucket <S3_BUCKET> --region <REGION>

預設：
  bucket = bitoguard-e15-data
  prefix = raw/
  region = ap-northeast-1

S3 結構（SageMaker training channel 對應）：
  s3://<bucket>/raw/user_info.parquet
  s3://<bucket>/raw/twd_transfer.parquet
  s3://<bucket>/raw/crypto_transfer.parquet
  s3://<bucket>/raw/usdt_twd_trading.parquet
  s3://<bucket>/raw/usdt_swap.parquet
  s3://<bucket>/raw/train_label.parquet
  s3://<bucket>/raw/predict_label.parquet
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import boto3
import httpx
import pandas as pd

SOURCE_URL = "https://aws-event-api.bitopro.com"

# 7 張表的 API endpoint 和主鍵
TABLES = [
    {"name": "user_info",        "endpoint": "/api/user_info",        "pk": "user_id"},
    {"name": "twd_transfer",     "endpoint": "/api/twd_transfer",     "pk": "id"},
    {"name": "crypto_transfer",  "endpoint": "/api/crypto_transfer",  "pk": "id"},
    {"name": "usdt_twd_trading", "endpoint": "/api/usdt_twd_trading", "pk": "id"},
    {"name": "usdt_swap",        "endpoint": "/api/usdt_swap",        "pk": "id"},
    {"name": "train_label",      "endpoint": "/api/train_label",      "pk": "user_id"},
    {"name": "predict_label",    "endpoint": "/api/predict_label",    "pk": "user_id"},
]

# 金額欄位需乘以 1e-8（BitoPro API 回傳整數格式）
AMOUNT_COLUMNS = {"ori_samount", "twd_srate", "amount", "fee", "total"}


def fetch_table(table: dict, base_url: str) -> pd.DataFrame:
    """從 BitoPro API 分頁下載一張表。

    API 回傳 JSON: {"data": [...], "next_cursor": "..." | null}
    """
    url = f"{base_url}{table['endpoint']}"
    all_rows = []
    cursor = None
    page = 0

    print(f"  [{table['name']}] 開始下載 ...")
    with httpx.Client(timeout=120.0) as client:
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(url, params=params)
            resp.raise_for_status()
            body = resp.json()

            rows = body.get("data", [])
            all_rows.extend(rows)
            page += 1

            cursor = body.get("next_cursor")
            if not cursor or not rows:
                break

            if page % 10 == 0:
                print(f"    第 {page} 頁，累計 {len(all_rows):,} 筆")

    df = pd.DataFrame(all_rows)
    print(f"  [{table['name']}] 共 {len(df):,} 筆")

    # 金額欄位 ×1e-8
    for col in AMOUNT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce") * 1e-8

    return df


def upload_to_s3(
    df: pd.DataFrame,
    table_name: str,
    bucket: str,
    prefix: str,
    s3_client,
    tmp_dir: Path,
) -> str:
    """將 DataFrame 存成 parquet 並上傳到 S3。"""
    local_path = tmp_dir / f"{table_name}.parquet"
    df.to_parquet(local_path, index=False, engine="pyarrow")
    s3_key = f"{prefix}{table_name}.parquet"
    s3_client.upload_file(str(local_path), bucket, s3_key)
    size_mb = local_path.stat().st_size / (1024 * 1024)
    print(f"  [{table_name}] 上傳 s3://{bucket}/{s3_key} ({size_mb:.1f} MB)")
    return s3_key


def main():
    parser = argparse.ArgumentParser(description="下載 BitoPro 資料並上傳到 S3")
    parser.add_argument("--bucket", default="bitoguard-e15-data", help="S3 bucket 名稱")
    parser.add_argument("--prefix", default="raw/", help="S3 key prefix")
    parser.add_argument("--region", default="ap-northeast-1", help="AWS 區域")
    parser.add_argument("--source-url", default=SOURCE_URL, help="BitoPro API base URL")
    parser.add_argument(
        "--local-dir",
        default=None,
        help="若指定，也將 parquet 存到此本機目錄（方便本機測試）",
    )
    args = parser.parse_args()

    print("=" * 56)
    print("BitoGuard E15 — 資料下載 & S3 上傳")
    print("=" * 56)
    print(f"  API: {args.source_url}")
    print(f"  S3:  s3://{args.bucket}/{args.prefix}")
    print("")

    # 建立 S3 bucket（如果不存在）
    s3 = boto3.client("s3", region_name=args.region)
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"[S3] Bucket '{args.bucket}' 已存在")
    except s3.exceptions.ClientError:
        print(f"[S3] 建立 bucket '{args.bucket}' ...")
        create_args = {"Bucket": args.bucket}
        # us-east-1 不能指定 LocationConstraint
        if args.region != "us-east-1":
            create_args["CreateBucketConfiguration"] = {
                "LocationConstraint": args.region,
            }
        s3.create_bucket(**create_args)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        for table in TABLES:
            try:
                df = fetch_table(table, args.source_url)
                upload_to_s3(df, table["name"], args.bucket, args.prefix, s3, tmp_dir)

                # 也存到本機
                if args.local_dir:
                    local_dir = Path(args.local_dir)
                    local_dir.mkdir(parents=True, exist_ok=True)
                    df.to_parquet(local_dir / f"{table['name']}.parquet", index=False)

            except Exception as e:
                print(f"  [錯誤] {table['name']}: {e}")
                sys.exit(1)

    print("")
    print("完成！所有 7 張表已上傳到 S3。")
    print(f"  s3://{args.bucket}/{args.prefix}")


if __name__ == "__main__":
    main()
