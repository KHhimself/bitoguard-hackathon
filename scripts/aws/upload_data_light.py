#!/usr/bin/env python3
"""逐表下載 BitoPro PostgREST 資料並上傳 S3。"""
from __future__ import annotations
import argparse, sys, tempfile
from pathlib import Path
import boto3, httpx, pandas as pd

SOURCE_URL = "https://aws-event-api.bitopro.com"

# PostgREST 表定義：(名稱, 排序欄位, 每頁筆數)
TABLES = [
    ("user_info",        "user_id",    1000),
    ("twd_transfer",     "id",         1000),
    ("crypto_transfer",  "id",         1000),
    ("usdt_twd_trading", "id",         1000),
    ("usdt_swap",        "id",         1000),
    ("train_label",      "user_id",    5000),
    ("predict_label",    "user_id",    5000),
]


def fetch_table(base_url: str, name: str, sort_field: str, page_size: int) -> pd.DataFrame:
    """PostgREST 分頁下載。"""
    url = f"{base_url}/{name}"
    rows = []
    offset = 0
    with httpx.Client(timeout=60.0) as client:
        while True:
            params = [
                ("order", f"{sort_field}.asc"),
                ("limit", page_size),
                ("offset", offset),
            ]
            resp = client.get(url, params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)
            if offset % 10000 == 0:
                print(f"    {offset:,} 筆 ...", flush=True)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", default="bitoguard-e15-data")
    parser.add_argument("--prefix", default="raw/")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"[S3] Bucket '{args.bucket}' exists")
    except Exception:
        create_args = {"Bucket": args.bucket}
        if args.region != "us-east-1":
            create_args["CreateBucketConfiguration"] = {"LocationConstraint": args.region}
        s3.create_bucket(**create_args)
        print(f"[S3] Created '{args.bucket}'")

    for name, sort_field, page_size in TABLES:
        print(f"  [{name}] downloading ...", flush=True)
        try:
            df = fetch_table(SOURCE_URL, name, sort_field, page_size)
            print(f"  [{name}] {len(df):,} rows")
            with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
                df.to_parquet(tmp.name, index=False, engine="pyarrow")
                s3_key = f"{args.prefix}{name}.parquet"
                s3.upload_file(tmp.name, args.bucket, s3_key)
                mb = Path(tmp.name).stat().st_size / (1024*1024)
                print(f"  [{name}] → s3://{args.bucket}/{s3_key} ({mb:.1f} MB)")
            del df
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            sys.exit(1)
    print("\nDone!")


if __name__ == "__main__":
    main()
