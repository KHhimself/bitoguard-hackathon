"""
Lambda function for registering models in SageMaker Model Registry.

This function registers trained models with metadata, metrics, and lineage information.
"""
import json
import logging
import boto3
from datetime import datetime
from typing import Dict, Any, Optional, List

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sagemaker = boto3.client('sagemaker')
s3 = boto3.client('s3')


def extract_training_metrics(training_job_name: str) -> Dict[str, Any]:
    """
    Extract metrics from a training job.
    
    Args:
        training_job_name: Name of the training job
        
    Returns:
        Dictionary of metrics
    """
    logger.info(f"Extracting metrics from training job: {training_job_name}")
    
    try:
        response = sagemaker.describe_training_job(
            TrainingJobName=training_job_name
        )
        
        metrics = {}
        for metric in response.get('FinalMetricDataList', []):
            metrics[metric['MetricName']] = {
                'value': metric['Value'],
                'timestamp': metric['Timestamp'].isoformat()
            }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error extracting metrics: {e}")
        return {}


def extract_hyperparameters(training_job_name: str) -> Dict[str, str]:
    """
    Extract hyperparameters from a training job.
    
    Args:
        training_job_name: Name of the training job
        
    Returns:
        Dictionary of hyperparameters
    """
    logger.info(f"Extracting hyperparameters from training job: {training_job_name}")
    
    try:
        response = sagemaker.describe_training_job(
            TrainingJobName=training_job_name
        )
        
        return response.get('HyperParameters', {})
        
    except Exception as e:
        logger.error(f"Error extracting hyperparameters: {e}")
        return {}


def register_model_version(
    model_package_group_name: str,
    model_type: str,
    training_job_name: str,
    model_data_url: str,
    inference_image_uri: str,
    metrics: Dict[str, Any],
    hyperparameters: Dict[str, str],
    approval_status: str = "PendingManualApproval"
) -> str:
    """
    Register a model version in the model registry.
    
    Args:
        model_package_group_name: Name of the model package group
        model_type: Type of model (lgbm, catboost, iforest)
        training_job_name: Name of the training job
        model_data_url: S3 URL to model artifacts
        inference_image_uri: Container image for inference
        metrics: Training metrics
        hyperparameters: Model hyperparameters
        approval_status: Initial approval status
        
    Returns:
        Model package ARN
    """
    logger.info(f"Registering model version for {model_type}")
    
    # Prepare model metrics for registry
    model_metrics = {
        'ModelQuality': {
            'Statistics': {
                'ContentType': 'application/json',
                'S3Uri': f"s3://placeholder/metrics/{training_job_name}.json"
            }
        }
    }
    
    # Prepare metadata
    customer_metadata = {
        'model_type': model_type,
        'training_job_name': training_job_name,
        'registration_timestamp': datetime.utcnow().isoformat(),
        'framework': 'lightgbm' if model_type == 'lgbm' else 'catboost' if model_type == 'catboost' else 'sklearn'
    }
    
    # Add metrics to metadata
    for metric_name, metric_data in metrics.items():
        customer_metadata[f'metric_{metric_name}'] = str(metric_data.get('value', ''))
    
    # Add key hyperparameters to metadata (limit to 50 chars per value)
    for hp_name, hp_value in list(hyperparameters.items())[:10]:
        customer_metadata[f'hp_{hp_name}'] = str(hp_value)[:50]
    
    try:
        response = sagemaker.create_model_package(
            ModelPackageGroupName=model_package_group_name,
            ModelPackageDescription=f"BitoGuard {model_type} model trained on {datetime.utcnow().strftime('%Y-%m-%d')}",
            InferenceSpecification={
                'Containers': [
                    {
                        'Image': inference_image_uri,
                        'ModelDataUrl': model_data_url
                    }
                ],
                'SupportedContentTypes': ['application/json', 'application/x-parquet'],
                'SupportedResponseMIMETypes': ['application/json']
            },
            ModelApprovalStatus=approval_status,
            CustomerMetadataProperties=customer_metadata,
            ModelMetrics=model_metrics
        )
        
        model_package_arn = response['ModelPackageArn']
        logger.info(f"Registered model package: {model_package_arn}")
        
        return model_package_arn
        
    except Exception as e:
        logger.error(f"Error registering model: {e}")
        raise


def save_registration_record(
    bucket_name: str,
    model_type: str,
    model_package_arn: str,
    training_job_name: str,
    metrics: Dict[str, Any],
    hyperparameters: Dict[str, str]
) -> str:
    """
    Save model registration record to S3.
    
    Args:
        bucket_name: S3 bucket name
        model_type: Type of model
        model_package_arn: ARN of registered model package
        training_job_name: Name of training job
        metrics: Training metrics
        hyperparameters: Model hyperparameters
        
    Returns:
        S3 URI of saved record
    """
    logger.info(f"Saving registration record to S3")
    
    record = {
        'model_package_arn': model_package_arn,
        'model_type': model_type,
        'training_job_name': training_job_name,
        'registration_timestamp': datetime.utcnow().isoformat(),
        'metrics': metrics,
        'hyperparameters': hyperparameters
    }
    
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    s3_key = f"model-registry/{model_type}/{timestamp}_registration.json"
    
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json.dumps(record, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        s3_uri = f"s3://{bucket_name}/{s3_key}"
        logger.info(f"Saved registration record to: {s3_uri}")
        
        return s3_uri
        
    except Exception as e:
        logger.error(f"Error saving registration record: {e}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for model registration.
    
    Expected event format:
    {
        "model_type": "lgbm",
        "training_job_name": "bitoguard-lgbm-...",
        "model_data_url": "s3://bucket/models/model.tar.gz",
        "inference_image_uri": "account.dkr.ecr.region.amazonaws.com/bitoguard:inference",
        "model_package_group_name": "bitoguard-ml-lgbm-models",
        "bucket_name": "bitoguard-ml-artifacts",
        "approval_status": "PendingManualApproval"
    }
    
    Returns:
    {
        "statusCode": 200,
        "body": {
            "model_package_arn": "arn:aws:sagemaker:...",
            "registration_record_uri": "s3://..."
        }
    }
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract parameters
        model_type = event.get('model_type')
        training_job_name = event.get('training_job_name')
        model_data_url = event.get('model_data_url')
        inference_image_uri = event.get('inference_image_uri')
        model_package_group_name = event.get('model_package_group_name')
        bucket_name = event.get('bucket_name')
        approval_status = event.get('approval_status', 'PendingManualApproval')
        
        # Validate required parameters
        if not all([model_type, training_job_name, model_data_url, 
                   inference_image_uri, model_package_group_name, bucket_name]):
            raise ValueError("Missing required parameters")
        
        # Extract metrics and hyperparameters
        metrics = extract_training_metrics(training_job_name)
        hyperparameters = extract_hyperparameters(training_job_name)
        
        # Register model
        model_package_arn = register_model_version(
            model_package_group_name=model_package_group_name,
            model_type=model_type,
            training_job_name=training_job_name,
            model_data_url=model_data_url,
            inference_image_uri=inference_image_uri,
            metrics=metrics,
            hyperparameters=hyperparameters,
            approval_status=approval_status
        )
        
        # Save registration record
        registration_record_uri = save_registration_record(
            bucket_name=bucket_name,
            model_type=model_type,
            model_package_arn=model_package_arn,
            training_job_name=training_job_name,
            metrics=metrics,
            hyperparameters=hyperparameters
        )
        
        logger.info(f"Model registration completed successfully")
        
        return {
            'statusCode': 200,
            'body': {
                'model_package_arn': model_package_arn,
                'registration_record_uri': registration_record_uri,
                'metrics': metrics,
                'approval_status': approval_status
            }
        }
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {e}", exc_info=True)
        
        return {
            'statusCode': 500,
            'body': {
                'error': str(e),
                'error_type': type(e).__name__
            }
        }
