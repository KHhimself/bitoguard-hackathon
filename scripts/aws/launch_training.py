#!/usr/bin/env python3
"""
啟動 SageMaker Training Job 跑 E15 AML 管線。

用法：
  python scripts/aws/launch_training.py \\
    --account-id 123456789012 \\
    --region ap-northeast-1 \\
    --bucket bitoguard-e15-data \\
    --instance-type ml.m5.xlarge

此腳本：
  1. 建立 SageMaker Training Job
  2. 輸入：S3 上的 7 張 parquet 表（channel="raw"）
  3. 輸出：model.tar.gz → S3（包含所有模型 + bundle + serve 程式碼）
  4. 額外輸出：submission CSV → S3
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import boto3


def create_training_job(
    sm_client,
    job_name: str,
    image_uri: str,
    role_arn: str,
    data_s3_uri: str,
    output_s3_uri: str,
    instance_type: str,
    volume_size_gb: int,
    max_runtime_s: int,
) -> str:
    """建立 SageMaker Training Job。"""
    sm_client.create_training_job(
        TrainingJobName=job_name,
        AlgorithmSpecification={
            "TrainingImage": image_uri,
            "TrainingInputMode": "File",
        },
        RoleArn=role_arn,
        InputDataConfig=[
            {
                "ChannelName": "raw",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": data_s3_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "ContentType": "application/x-parquet",
                "CompressionType": "None",
            }
        ],
        OutputDataConfig={
            "S3OutputPath": output_s3_uri,
        },
        ResourceConfig={
            "InstanceType": instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": volume_size_gb,
        },
        StoppingCondition={
            "MaxRuntimeInSeconds": max_runtime_s,
        },
        Tags=[
            {"Key": "Project", "Value": "BitoGuard-E15"},
            {"Key": "Pipeline", "Value": "AML-Training"},
        ],
    )
    return job_name


def wait_for_training(sm_client, job_name: str, poll_interval: int = 30) -> dict:
    """等待 Training Job 完成。"""
    print(f"\n等待 Training Job '{job_name}' 完成 ...")
    while True:
        resp = sm_client.describe_training_job(TrainingJobName=job_name)
        status = resp["TrainingJobStatus"]
        secondary = resp.get("SecondaryStatus", "")

        elapsed = ""
        if "TrainingStartTime" in resp:
            delta = datetime.now(timezone.utc) - resp["TrainingStartTime"]
            elapsed = f" ({int(delta.total_seconds())}s)"

        print(f"  狀態: {status} / {secondary}{elapsed}")

        if status in ("Completed", "Failed", "Stopped"):
            return resp

        time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="啟動 E15 SageMaker Training Job")
    parser.add_argument("--account-id", required=True, help="AWS 帳號 ID")
    parser.add_argument("--region", default="ap-northeast-1", help="AWS 區域")
    parser.add_argument("--bucket", default="bitoguard-e15-data", help="S3 bucket")
    parser.add_argument("--data-prefix", default="raw/", help="S3 資料 prefix")
    parser.add_argument("--output-prefix", default="training-output/", help="S3 輸出 prefix")
    parser.add_argument("--instance-type", default="ml.m5.xlarge", help="訓練 instance 類型")
    parser.add_argument("--volume-size", type=int, default=30, help="EBS volume 大小 (GB)")
    parser.add_argument("--max-runtime", type=int, default=7200, help="最長執行時間 (秒)")
    parser.add_argument("--role-arn", default=None, help="SageMaker execution role ARN")
    parser.add_argument("--image-tag", default="latest", help="Docker image tag")
    parser.add_argument("--no-wait", action="store_true", help="不等待訓練完成")
    args = parser.parse_args()

    # 組合 image URI
    image_uri = (
        f"{args.account_id}.dkr.ecr.{args.region}.amazonaws.com/"
        f"bitoguard-e15-training:{args.image_tag}"
    )
    data_s3_uri = f"s3://{args.bucket}/{args.data_prefix}"
    output_s3_uri = f"s3://{args.bucket}/{args.output_prefix}"

    # 自動偵測 SageMaker execution role
    role_arn = args.role_arn
    if not role_arn:
        iam = boto3.client("iam", region_name=args.region)
        # 嘗試常見的 role 名稱
        for role_name in ["SageMakerExecutionRole", "AmazonSageMaker-ExecutionRole",
                          "bitoguard-sagemaker-role", "SageMakerRole"]:
            try:
                resp = iam.get_role(RoleName=role_name)
                role_arn = resp["Role"]["Arn"]
                print(f"[自動偵測] SageMaker Role: {role_arn}")
                break
            except iam.exceptions.NoSuchEntityException:
                continue
        if not role_arn:
            # 列出所有包含 "sagemaker" 的 role
            paginator = iam.get_paginator("list_roles")
            for page in paginator.paginate():
                for role in page["Roles"]:
                    if "sagemaker" in role["RoleName"].lower():
                        role_arn = role["Arn"]
                        print(f"[自動偵測] SageMaker Role: {role_arn}")
                        break
                if role_arn:
                    break

        if not role_arn:
            print("[錯誤] 找不到 SageMaker execution role。")
            print("  請用 --role-arn 指定，或建立 SageMakerExecutionRole。")
            return

    # 產生唯一 job name
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_name = f"bitoguard-e15-{now_str}"

    print("=" * 56)
    print("BitoGuard E15 — SageMaker Training Job")
    print("=" * 56)
    print(f"  Job Name:    {job_name}")
    print(f"  Image:       {image_uri}")
    print(f"  Instance:    {args.instance_type}")
    print(f"  Input:       {data_s3_uri}")
    print(f"  Output:      {output_s3_uri}")
    print(f"  Role:        {role_arn}")
    print(f"  Max Runtime: {args.max_runtime}s")
    print("")

    # 建立 Training Job
    sm = boto3.client("sagemaker", region_name=args.region)
    create_training_job(
        sm_client=sm,
        job_name=job_name,
        image_uri=image_uri,
        role_arn=role_arn,
        data_s3_uri=data_s3_uri,
        output_s3_uri=output_s3_uri,
        instance_type=args.instance_type,
        volume_size_gb=args.volume_size,
        max_runtime_s=args.max_runtime,
    )
    print(f"Training Job '{job_name}' 已建立！")

    if args.no_wait:
        print(f"\n使用以下指令查看狀態:")
        print(f"  aws sagemaker describe-training-job --training-job-name {job_name} --region {args.region}")
        return

    # 等待完成
    result = wait_for_training(sm, job_name)
    status = result["TrainingJobStatus"]

    if status == "Completed":
        model_s3 = result.get("ModelArtifacts", {}).get("S3ModelArtifacts", "N/A")
        print(f"\n訓練成功！")
        print(f"  Model Artifacts: {model_s3}")
        print(f"\n下一步：部署 endpoint")
        print(f"  python scripts/aws/deploy_endpoint.py \\")
        print(f"    --account-id {args.account_id} \\")
        print(f"    --region {args.region} \\")
        print(f"    --model-data {model_s3}")
    else:
        failure_reason = result.get("FailureReason", "未知")
        print(f"\n訓練失敗！狀態: {status}")
        print(f"  原因: {failure_reason}")
        print(f"\n查看 CloudWatch Logs:")
        print(f"  aws logs get-log-events \\")
        print(f"    --log-group-name /aws/sagemaker/TrainingJobs \\")
        print(f"    --log-stream-name {job_name}/algo-1 \\")
        print(f"    --region {args.region}")


if __name__ == "__main__":
    main()
