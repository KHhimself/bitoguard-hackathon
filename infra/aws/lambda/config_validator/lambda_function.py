"""
Configuration Validator Lambda Function

Validates SSM parameters before ML pipeline execution to ensure
all required configuration is present and valid.
"""

import json
import logging
import os
from typing import Dict, Any, List

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
ssm_client = boto3.client('ssm')
s3_client = boto3.client('s3')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for configuration validation
    
    Expected event structure:
    {
        "parameter_prefix": "/bitoguard/ml-pipeline"
    }
    """
    try:
        parameter_prefix = event.get('parameter_prefix', '/bitoguard/ml-pipeline')
        
        logger.info(f"Validating configuration with prefix: {parameter_prefix}")
        
        # Validate required parameters
        validation_errors = []
        
        # Check scheduling parameters
        validation_errors.extend(validate_scheduling_params(parameter_prefix))
        
        # Check training hyperparameters
        validation_errors.extend(validate_training_params(parameter_prefix))
        
        # Check threshold parameters
        validation_errors.extend(validate_threshold_params(parameter_prefix))
        
        # Check resource allocation parameters
        validation_errors.extend(validate_resource_params(parameter_prefix))
        
        # Check S3 bucket existence
        validation_errors.extend(validate_s3_resources(parameter_prefix))
        
        if validation_errors:
            logger.error(f"Configuration validation failed with {len(validation_errors)} errors")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'valid': False,
                    'errors': validation_errors
                })
            }
        
        logger.info("Configuration validation passed")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'valid': True,
                'message': 'All configuration parameters are valid'
            })
        }
    
    except Exception as e:
        logger.error(f"Configuration validation failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'valid': False,
                'errors': [f"Validation error: {str(e)}"]
            })
        }


def get_parameter(name: str) -> str:
    """Get parameter value from SSM"""
    try:
        response = ssm_client.get_parameter(Name=name)
        return response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            raise ValueError(f"Required parameter not found: {name}")
        raise


def validate_scheduling_params(prefix: str) -> List[str]:
    """Validate scheduling parameters"""
    errors = []
    
    try:
        # Check daily schedule
        daily_schedule = get_parameter(f"{prefix}/scheduling/daily_full_pipeline_cron")
        if not daily_schedule:
            errors.append("Daily pipeline schedule is empty")
        
        # Check incremental schedule
        incremental_schedule = get_parameter(f"{prefix}/scheduling/incremental_refresh_cron")
        if not incremental_schedule:
            errors.append("Incremental refresh schedule is empty")
    
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"Error validating scheduling params: {str(e)}")
    
    return errors


def validate_training_params(prefix: str) -> List[str]:
    """Validate training hyperparameters"""
    errors = []
    
    try:
        # LightGBM parameters
        lgbm_n_estimators = int(get_parameter(f"{prefix}/training/lgbm/n_estimators"))
        if lgbm_n_estimators < 10 or lgbm_n_estimators > 10000:
            errors.append(f"LightGBM n_estimators out of range: {lgbm_n_estimators}")
        
        lgbm_learning_rate = float(get_parameter(f"{prefix}/training/lgbm/learning_rate"))
        if lgbm_learning_rate <= 0 or lgbm_learning_rate > 1:
            errors.append(f"LightGBM learning_rate out of range: {lgbm_learning_rate}")
        
        # CatBoost parameters
        catboost_iterations = int(get_parameter(f"{prefix}/training/catboost/iterations"))
        if catboost_iterations < 10 or catboost_iterations > 10000:
            errors.append(f"CatBoost iterations out of range: {catboost_iterations}")
        
        # IsolationForest parameters
        iforest_n_estimators = int(get_parameter(f"{prefix}/training/iforest/n_estimators"))
        if iforest_n_estimators < 10 or iforest_n_estimators > 1000:
            errors.append(f"IsolationForest n_estimators out of range: {iforest_n_estimators}")
        
        iforest_contamination = float(get_parameter(f"{prefix}/training/iforest/contamination"))
        if iforest_contamination <= 0 or iforest_contamination > 0.5:
            errors.append(f"IsolationForest contamination out of range: {iforest_contamination}")
    
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"Error validating training params: {str(e)}")
    
    return errors


def validate_threshold_params(prefix: str) -> List[str]:
    """Validate threshold parameters"""
    errors = []
    
    try:
        # Drift thresholds
        feature_drift = float(get_parameter(f"{prefix}/thresholds/feature_drift_kl"))
        if feature_drift < 0 or feature_drift > 1:
            errors.append(f"Feature drift threshold out of range: {feature_drift}")
        
        prediction_drift = float(get_parameter(f"{prefix}/thresholds/prediction_drift_percentage"))
        if prediction_drift < 0 or prediction_drift > 1:
            errors.append(f"Prediction drift threshold out of range: {prediction_drift}")
        
        # Alert threshold
        alert_threshold = float(get_parameter(f"{prefix}/thresholds/alert_risk_score"))
        if alert_threshold < 0 or alert_threshold > 1:
            errors.append(f"Alert risk score threshold out of range: {alert_threshold}")
    
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"Error validating threshold params: {str(e)}")
    
    return errors


def validate_resource_params(prefix: str) -> List[str]:
    """Validate resource allocation parameters"""
    errors = []
    
    try:
        # SageMaker instance type
        instance_type = get_parameter(f"{prefix}/resources/sagemaker_instance_type")
        valid_types = ['ml.m5.large', 'ml.m5.xlarge', 'ml.m5.2xlarge', 'ml.c5.xlarge', 'ml.c5.2xlarge']
        if instance_type not in valid_types:
            errors.append(f"Invalid SageMaker instance type: {instance_type}")
        
        # Max runtime
        max_runtime = int(get_parameter(f"{prefix}/resources/sagemaker_max_runtime_seconds"))
        if max_runtime < 300 or max_runtime > 86400:  # 5 min to 24 hours
            errors.append(f"SageMaker max runtime out of range: {max_runtime}")
        
        # ECS task CPU/memory
        ecs_cpu = int(get_parameter(f"{prefix}/resources/ecs_task_cpu"))
        valid_cpu = [256, 512, 1024, 2048, 4096]
        if ecs_cpu not in valid_cpu:
            errors.append(f"Invalid ECS task CPU: {ecs_cpu}")
        
        ecs_memory = int(get_parameter(f"{prefix}/resources/ecs_task_memory"))
        if ecs_memory < 512 or ecs_memory > 30720:
            errors.append(f"ECS task memory out of range: {ecs_memory}")
    
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"Error validating resource params: {str(e)}")
    
    return errors


def validate_s3_resources(prefix: str) -> List[str]:
    """Validate S3 bucket existence"""
    errors = []
    
    try:
        # Get bucket name from parameter
        bucket_name = get_parameter(f"{prefix}/s3/artifacts_bucket")
        
        # Check if bucket exists
        try:
            s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                errors.append(f"S3 bucket does not exist: {bucket_name}")
            elif error_code == '403':
                errors.append(f"No permission to access S3 bucket: {bucket_name}")
            else:
                errors.append(f"Error accessing S3 bucket {bucket_name}: {error_code}")
    
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"Error validating S3 resources: {str(e)}")
    
    return errors
