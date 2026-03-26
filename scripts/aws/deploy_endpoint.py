#!/usr/bin/env python3
"""
部署 E15 模型到 SageMaker Endpoint。

用法：
  python scripts/aws/deploy_endpoint.py \\
    --account-id 123456789012 \\
    --region ap-northeast-1 \\
    --model-data s3://bitoguard-e15-data/training-output/bitoguard-e15-xxx/output/model.tar.gz

此腳本依序執行：
  1. CreateModel（指定 inference image + model.tar.gz）
  2. CreateEndpointConfig（ml.c5.large）
  3. CreateEndpoint
  4. 等待 InService
  5. 測試 /ping
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import boto3


def create_model(
    sm_client,
    model_name: str,
    image_uri: str,
    model_data_url: str,
    role_arn: str,
) -> str:
    """建立 SageMaker Model。

    Inference 容器使用和 Training 相同的 image，
    但 SageMaker 會改用 gunicorn 啟動 serve_e15.py。
    """
    sm_client.create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": image_uri,
            "ModelDataUrl": model_data_url,
            "Environment": {
                # SageMaker inference 會用 gunicorn 啟動此模組
                "SAGEMAKER_PROGRAM": "serve_e15.py",
                "SM_MODEL_DIR": "/opt/ml/model",
            },
        },
        ExecutionRoleArn=role_arn,
        Tags=[
            {"Key": "Project", "Value": "BitoGuard-E15"},
        ],
    )
    print(f"  Model '{model_name}' 已建立")
    return model_name


def create_endpoint_config(
    sm_client,
    config_name: str,
    model_name: str,
    instance_type: str,
    initial_instance_count: int,
) -> str:
    """建立 Endpoint Configuration。"""
    sm_client.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[
            {
                "VariantName": "primary",
                "ModelName": model_name,
                "InstanceType": instance_type,
                "InitialInstanceCount": initial_instance_count,
                "InitialVariantWeight": 1.0,
            }
        ],
        Tags=[
            {"Key": "Project", "Value": "BitoGuard-E15"},
        ],
    )
    print(f"  EndpointConfig '{config_name}' 已建立")
    return config_name


def create_endpoint(sm_client, endpoint_name: str, config_name: str) -> str:
    """建立 Endpoint。"""
    sm_client.create_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=config_name,
        Tags=[
            {"Key": "Project", "Value": "BitoGuard-E15"},
        ],
    )
    print(f"  Endpoint '{endpoint_name}' 建立中 ...")
    return endpoint_name


def wait_for_endpoint(sm_client, endpoint_name: str, poll_interval: int = 30) -> dict:
    """等待 Endpoint 變成 InService。"""
    print(f"\n等待 Endpoint '{endpoint_name}' 上線 ...")
    while True:
        resp = sm_client.describe_endpoint(EndpointName=endpoint_name)
        status = resp["EndpointStatus"]
        print(f"  狀態: {status}")

        if status == "InService":
            return resp
        if status == "Failed":
            reason = resp.get("FailureReason", "未知")
            raise RuntimeError(f"Endpoint 建立失敗: {reason}")

        time.sleep(poll_interval)


def test_endpoint(runtime_client, endpoint_name: str) -> None:
    """發送測試請求驗證 endpoint。"""
    print(f"\n測試 Endpoint '{endpoint_name}' ...")

    # 空的 JSON body 來測 /ping via invoke_endpoint
    try:
        resp = runtime_client.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"instances": []}),
        )
        status_code = resp["ResponseMetadata"]["HTTPStatusCode"]
        body = resp["Body"].read().decode("utf-8")
        print(f"  HTTP {status_code}: {body[:200]}")
    except Exception as e:
        print(f"  測試請求失敗: {e}")
        print("  （這可能是正常的——空 instances 可能被拒絕）")


def find_role_arn(iam_client) -> str | None:
    """自動偵測 SageMaker execution role。"""
    for role_name in ["SageMakerExecutionRole", "AmazonSageMaker-ExecutionRole",
                      "bitoguard-sagemaker-role", "SageMakerRole"]:
        try:
            resp = iam_client.get_role(RoleName=role_name)
            return resp["Role"]["Arn"]
        except iam_client.exceptions.NoSuchEntityException:
            continue

    paginator = iam_client.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page["Roles"]:
            if "sagemaker" in role["RoleName"].lower():
                return role["Arn"]
    return None


def main():
    parser = argparse.ArgumentParser(description="部署 E15 到 SageMaker Endpoint")
    parser.add_argument("--account-id", required=True, help="AWS 帳號 ID")
    parser.add_argument("--region", default="ap-northeast-1", help="AWS 區域")
    parser.add_argument("--model-data", required=True,
                        help="model.tar.gz 的 S3 URI")
    parser.add_argument("--instance-type", default="ml.c5.large",
                        help="Endpoint instance 類型")
    parser.add_argument("--instance-count", type=int, default=1,
                        help="Endpoint instance 數量")
    parser.add_argument("--role-arn", default=None,
                        help="SageMaker execution role ARN")
    parser.add_argument("--image-tag", default="latest", help="Docker image tag")
    parser.add_argument("--endpoint-name", default=None,
                        help="Endpoint 名稱（預設自動產生）")
    parser.add_argument("--no-wait", action="store_true", help="不等待 endpoint 上線")
    args = parser.parse_args()

    image_uri = (
        f"{args.account_id}.dkr.ecr.{args.region}.amazonaws.com/"
        f"bitoguard-e15-training:{args.image_tag}"
    )

    # 偵測 role
    role_arn = args.role_arn
    if not role_arn:
        iam = boto3.client("iam", region_name=args.region)
        role_arn = find_role_arn(iam)
        if role_arn:
            print(f"[自動偵測] Role: {role_arn}")
        else:
            print("[錯誤] 找不到 SageMaker execution role。請用 --role-arn 指定。")
            return

    # 產生名稱
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    model_name = f"bitoguard-e15-{now_str}"
    config_name = f"bitoguard-e15-config-{now_str}"
    endpoint_name = args.endpoint_name or f"bitoguard-e15-endpoint"

    print("=" * 56)
    print("BitoGuard E15 — 部署 SageMaker Endpoint")
    print("=" * 56)
    print(f"  Model Name:    {model_name}")
    print(f"  Image:         {image_uri}")
    print(f"  Model Data:    {args.model_data}")
    print(f"  Instance:      {args.instance_type} × {args.instance_count}")
    print(f"  Endpoint:      {endpoint_name}")
    print("")

    sm = boto3.client("sagemaker", region_name=args.region)

    # Step 1: CreateModel
    print("[1/3] 建立 Model ...")
    create_model(sm, model_name, image_uri, args.model_data, role_arn)

    # Step 2: CreateEndpointConfig
    print("[2/3] 建立 EndpointConfig ...")
    create_endpoint_config(
        sm, config_name, model_name,
        args.instance_type, args.instance_count,
    )

    # Step 3: CreateEndpoint
    print("[3/3] 建立 Endpoint ...")

    # 檢查是否已存在（更新而非重建）
    try:
        sm.describe_endpoint(EndpointName=endpoint_name)
        print(f"  Endpoint '{endpoint_name}' 已存在，更新中 ...")
        sm.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=config_name,
        )
    except sm.exceptions.ClientError:
        create_endpoint(sm, endpoint_name, config_name)

    if args.no_wait:
        print(f"\nEndpoint 建立中。使用以下指令查看狀態:")
        print(f"  aws sagemaker describe-endpoint --endpoint-name {endpoint_name} --region {args.region}")
        return

    # 等待上線
    wait_for_endpoint(sm, endpoint_name)

    # 測試
    runtime = boto3.client("sagemaker-runtime", region_name=args.region)
    test_endpoint(runtime, endpoint_name)

    print(f"\nEndpoint 已上線！")
    print(f"  Endpoint Name: {endpoint_name}")
    print(f"\n測試推論:")
    print(f'  aws sagemaker-runtime invoke-endpoint \\')
    print(f'    --endpoint-name {endpoint_name} \\')
    print(f'    --content-type application/json \\')
    print(f'    --body \'{{"instances": [{{"user_id": "test"}}]}}\' \\')
    print(f'    --region {args.region} \\')
    print(f'    output.json')


if __name__ == "__main__":
    main()
