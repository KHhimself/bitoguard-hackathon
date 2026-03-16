"""
Lambda function to analyze hyperparameter tuning results.

This function extracts the best hyperparameters from completed tuning jobs
and saves the results to S3 for analysis and future use.
"""
import json
import logging
import boto3
from datetime import datetime
from typing import Dict, Any, List, Optional

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sagemaker = boto3.client('sagemaker')
s3 = boto3.client('s3')


def get_best_training_job(tuning_job_name: str) -> Dict[str, Any]:
    """
    Get the best training job from a hyperparameter tuning job.
    
    Args:
        tuning_job_name: Name of the tuning job
        
    Returns:
        Dictionary with best training job details
    """
    logger.info(f"Retrieving best training job for: {tuning_job_name}")
    
    try:
        response = sagemaker.describe_hyper_parameter_tuning_job(
            HyperParameterTuningJobName=tuning_job_name
        )
        
        if 'BestTrainingJob' not in response:
            raise ValueError(f"No best training job found for {tuning_job_name}")
        
        best_job = response['BestTrainingJob']
        
        return {
            'training_job_name': best_job['TrainingJobName'],
            'training_job_arn': best_job['TrainingJobArn'],
            'creation_time': best_job['CreationTime'].isoformat(),
            'training_start_time': best_job.get('TrainingStartTime', '').isoformat() if best_job.get('TrainingStartTime') else None,
            'training_end_time': best_job.get('TrainingEndTime', '').isoformat() if best_job.get('TrainingEndTime') else None,
            'training_job_status': best_job['TrainingJobStatus'],
            'tuned_hyperparameters': best_job.get('TunedHyperParameters', {}),
            'final_metric': best_job.get('FinalHyperParameterTuningJobObjectiveMetric', {})
        }
        
    except Exception as e:
        logger.error(f"Error retrieving best training job: {e}")
        raise


def get_training_job_details(training_job_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a training job.
    
    Args:
        training_job_name: Name of the training job
        
    Returns:
        Dictionary with training job details
    """
    logger.info(f"Retrieving training job details: {training_job_name}")
    
    try:
        response = sagemaker.describe_training_job(
            TrainingJobName=training_job_name
        )
        
        return {
            'training_job_name': response['TrainingJobName'],
            'training_job_arn': response['TrainingJobArn'],
            'model_artifacts': response.get('ModelArtifacts', {}).get('S3ModelArtifacts', ''),
            'training_job_status': response['TrainingJobStatus'],
            'secondary_status': response.get('SecondaryStatus', ''),
            'hyperparameters': response.get('HyperParameters', {}),
            'algorithm_specification': response.get('AlgorithmSpecification', {}),
            'resource_config': response.get('ResourceConfig', {}),
            'output_data_config': response.get('OutputDataConfig', {}),
            'billable_time_in_seconds': response.get('BillableTimeInSeconds', 0),
            'training_time_in_seconds': response.get('TrainingTimeInSeconds', 0),
            'final_metric_data_list': response.get('FinalMetricDataList', [])
        }
        
    except Exception as e:
        logger.error(f"Error retrieving training job details: {e}")
        raise


def get_all_training_jobs(tuning_job_name: str, max_results: int = 100) -> List[Dict[str, Any]]:
    """
    Get all training jobs from a tuning job.
    
    Args:
        tuning_job_name: Name of the tuning job
        max_results: Maximum number of results to return
        
    Returns:
        List of training job summaries
    """
    logger.info(f"Retrieving all training jobs for: {tuning_job_name}")
    
    try:
        training_jobs = []
        next_token = None
        
        while True:
            params = {
                'HyperParameterTuningJobName': tuning_job_name,
                'MaxResults': min(max_results - len(training_jobs), 100),
                'SortBy': 'FinalObjectiveMetricValue',
                'SortOrder': 'Descending'
            }
            
            if next_token:
                params['NextToken'] = next_token
            
            response = sagemaker.list_training_jobs_for_hyper_parameter_tuning_job(**params)
            
            for job in response.get('TrainingJobSummaries', []):
                training_jobs.append({
                    'training_job_name': job['TrainingJobName'],
                    'training_job_arn': job['TrainingJobArn'],
                    'creation_time': job['CreationTime'].isoformat(),
                    'training_start_time': job.get('TrainingStartTime', '').isoformat() if job.get('TrainingStartTime') else None,
                    'training_end_time': job.get('TrainingEndTime', '').isoformat() if job.get('TrainingEndTime') else None,
                    'training_job_status': job['TrainingJobStatus'],
                    'tuned_hyperparameters': job.get('TunedHyperParameters', {}),
                    'final_metric': job.get('FinalHyperParameterTuningJobObjectiveMetric', {})
                })
            
            next_token = response.get('NextToken')
            
            if not next_token or len(training_jobs) >= max_results:
                break
        
        logger.info(f"Retrieved {len(training_jobs)} training jobs")
        return training_jobs
        
    except Exception as e:
        logger.error(f"Error retrieving training jobs: {e}")
        raise


def save_tuning_results(
    bucket_name: str,
    tuning_job_name: str,
    best_job: Dict[str, Any],
    best_job_details: Dict[str, Any],
    all_jobs: List[Dict[str, Any]]
) -> str:
    """
    Save tuning results to S3.
    
    Args:
        bucket_name: S3 bucket name
        tuning_job_name: Name of the tuning job
        best_job: Best training job summary
        best_job_details: Detailed information about best job
        all_jobs: List of all training jobs
        
    Returns:
        S3 URI of saved results
    """
    logger.info(f"Saving tuning results to S3: {bucket_name}")
    
    # Prepare results document
    results = {
        'tuning_job_name': tuning_job_name,
        'analysis_timestamp': datetime.utcnow().isoformat(),
        'best_training_job': {
            'summary': best_job,
            'details': best_job_details
        },
        'all_training_jobs': all_jobs,
        'statistics': {
            'total_jobs': len(all_jobs),
            'completed_jobs': sum(1 for j in all_jobs if j['training_job_status'] == 'Completed'),
            'failed_jobs': sum(1 for j in all_jobs if j['training_job_status'] == 'Failed'),
            'stopped_jobs': sum(1 for j in all_jobs if j['training_job_status'] == 'Stopped')
        }
    }
    
    # Generate S3 key
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    s3_key = f"tuning-analysis/{tuning_job_name}/{timestamp}_analysis.json"
    
    try:
        # Upload to S3
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json.dumps(results, indent=2).encode('utf-8'),
            ContentType='application/json'
        )
        
        s3_uri = f"s3://{bucket_name}/{s3_key}"
        logger.info(f"Saved tuning results to: {s3_uri}")
        
        return s3_uri
        
    except Exception as e:
        logger.error(f"Error saving tuning results to S3: {e}")
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for analyzing hyperparameter tuning results.
    
    Expected event format:
    {
        "tuning_job_name": "bitoguard-lgbm-tuning-...",
        "bucket_name": "bitoguard-ml-artifacts",
        "include_all_jobs": true
    }
    
    Returns:
    {
        "statusCode": 200,
        "body": {
            "best_training_job_name": "...",
            "best_hyperparameters": {...},
            "final_metric_value": 0.95,
            "results_s3_uri": "s3://..."
        }
    }
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract parameters
        tuning_job_name = event.get('tuning_job_name')
        bucket_name = event.get('bucket_name')
        include_all_jobs = event.get('include_all_jobs', True)
        
        if not tuning_job_name:
            raise ValueError("tuning_job_name is required")
        
        if not bucket_name:
            raise ValueError("bucket_name is required")
        
        # Get best training job
        best_job = get_best_training_job(tuning_job_name)
        
        # Get detailed information about best job
        best_job_details = get_training_job_details(best_job['training_job_name'])
        
        # Get all training jobs if requested
        all_jobs = []
        if include_all_jobs:
            all_jobs = get_all_training_jobs(tuning_job_name)
        
        # Save results to S3
        results_s3_uri = save_tuning_results(
            bucket_name=bucket_name,
            tuning_job_name=tuning_job_name,
            best_job=best_job,
            best_job_details=best_job_details,
            all_jobs=all_jobs
        )
        
        # Prepare response
        response_body = {
            'best_training_job_name': best_job['training_job_name'],
            'best_hyperparameters': best_job['tuned_hyperparameters'],
            'final_metric': best_job['final_metric'],
            'model_artifacts_uri': best_job_details['model_artifacts'],
            'results_s3_uri': results_s3_uri,
            'total_training_jobs': len(all_jobs) if include_all_jobs else None
        }
        
        logger.info(f"Analysis completed successfully")
        
        return {
            'statusCode': 200,
            'body': response_body
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
