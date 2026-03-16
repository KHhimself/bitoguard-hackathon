"""
Drift Detection Lambda Function

Detects feature drift and prediction drift by comparing current and baseline
feature distributions using KL divergence and chi-square tests.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Tuple

import boto3
import pandas as pd
import numpy as np
from scipy.stats import chi2_contingency
from scipy.special import kl_div

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')
cloudwatch_client = boto3.client('cloudwatch')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for drift detection
    
    Expected event structure:
    {
        "baseline_snapshot_id": "20260101T000000Z",
        "current_snapshot_id": "20260315T000000Z",
        "bucket_name": "bitoguard-ml-artifacts",
        "drift_threshold": 0.1,
        "prediction_drift_threshold": 0.15
    }
    """
    try:
        # Extract parameters
        baseline_id = event['baseline_snapshot_id']
        current_id = event['current_snapshot_id']
        bucket_name = event['bucket_name']
        drift_threshold = event.get('drift_threshold', 0.1)
        pred_drift_threshold = event.get('prediction_drift_threshold', 0.15)
        
        logger.info(f"Starting drift detection: baseline={baseline_id}, current={current_id}")
        
        # Load feature snapshots
        baseline_df = load_feature_snapshot(bucket_name, baseline_id)
        current_df = load_feature_snapshot(bucket_name, current_id)
        
        logger.info(f"Loaded snapshots: baseline={len(baseline_df)} rows, current={len(current_df)} rows")
        
        # Detect feature drift
        drift_results = detect_feature_drift(baseline_df, current_df, drift_threshold)
        
        # Detect prediction drift (if risk scores available)
        prediction_drift = None
        if 'risk_score' in baseline_df.columns and 'risk_score' in current_df.columns:
            prediction_drift = detect_prediction_drift(
                baseline_df['risk_score'],
                current_df['risk_score'],
                pred_drift_threshold
            )
        
        # Publish CloudWatch metrics
        publish_drift_metrics(drift_results, prediction_drift)
        
        # Check if alerting is needed
        alert_needed = (
            drift_results['drifted_feature_count'] > 5 or
            (prediction_drift and prediction_drift['drift_percentage'] > pred_drift_threshold)
        )
        
        if alert_needed:
            send_drift_alert(drift_results, prediction_drift, bucket_name)
        
        # Save drift report to S3
        report_path = save_drift_report(drift_results, prediction_drift, bucket_name, current_id)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Drift detection completed',
                'drifted_features': drift_results['drifted_feature_count'],
                'total_features': drift_results['total_features'],
                'prediction_drift': prediction_drift['drift_percentage'] if prediction_drift else None,
                'alert_sent': alert_needed,
                'report_path': report_path
            })
        }
    
    except Exception as e:
        logger.error(f"Drift detection failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }


def load_feature_snapshot(bucket_name: str, snapshot_id: str) -> pd.DataFrame:
    """Load feature snapshot from S3"""
    # Parse snapshot ID to get date partition
    dt = datetime.strptime(snapshot_id, "%Y%m%dT%H%M%SZ")
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    day = dt.strftime("%d")
    
    s3_key = f"features/year={year}/month={month}/day={day}/{snapshot_id}.parquet"
    
    logger.info(f"Loading snapshot from s3://{bucket_name}/{s3_key}")
    
    # Download from S3
    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    df = pd.read_parquet(response['Body'], engine='pyarrow')
    
    return df


def detect_feature_drift(
    baseline_df: pd.DataFrame,
    current_df: pd.DataFrame,
    threshold: float
) -> Dict[str, Any]:
    """
    Detect feature drift using KL divergence for numerical features
    and chi-square test for categorical features
    """
    drift_results = {
        'total_features': 0,
        'drifted_feature_count': 0,
        'drifted_features': [],
        'feature_drift_scores': {}
    }
    
    # Get common columns (exclude metadata columns)
    exclude_cols = {'user_id', 'feature_snapshot_id', 'snapshot_date', 'feature_version', 'risk_score'}
    common_cols = set(baseline_df.columns) & set(current_df.columns) - exclude_cols
    
    drift_results['total_features'] = len(common_cols)
    
    for col in common_cols:
        try:
            # Check if numerical or categorical
            if pd.api.types.is_numeric_dtype(baseline_df[col]):
                # Numerical feature - use KL divergence
                drift_score = compute_kl_divergence(
                    baseline_df[col].values,
                    current_df[col].values
                )
            else:
                # Categorical feature - use chi-square test
                drift_score = compute_chi_square(
                    baseline_df[col].values,
                    current_df[col].values
                )
            
            drift_results['feature_drift_scores'][col] = drift_score
            
            # Check if drifted
            if drift_score > threshold:
                drift_results['drifted_feature_count'] += 1
                drift_results['drifted_features'].append({
                    'feature': col,
                    'drift_score': drift_score
                })
        
        except Exception as e:
            logger.warning(f"Failed to compute drift for feature {col}: {e}")
    
    # Sort drifted features by score
    drift_results['drifted_features'].sort(key=lambda x: x['drift_score'], reverse=True)
    
    return drift_results


def compute_kl_divergence(baseline: np.ndarray, current: np.ndarray, bins: int = 50) -> float:
    """
    Compute KL divergence between two distributions
    
    Returns average of KL(baseline||current) and KL(current||baseline)
    """
    # Remove NaN values
    baseline = baseline[~np.isnan(baseline)]
    current = current[~np.isnan(current)]
    
    if len(baseline) == 0 or len(current) == 0:
        return 0.0
    
    # Create histograms with same bins
    min_val = min(baseline.min(), current.min())
    max_val = max(baseline.max(), current.max())
    
    # Handle constant features
    if min_val == max_val:
        return 0.0
    
    bin_edges = np.linspace(min_val, max_val, bins + 1)
    
    baseline_hist, _ = np.histogram(baseline, bins=bin_edges, density=True)
    current_hist, _ = np.histogram(current, bins=bin_edges, density=True)
    
    # Add small epsilon to avoid division by zero
    epsilon = 1e-10
    baseline_hist = baseline_hist + epsilon
    current_hist = current_hist + epsilon
    
    # Normalize
    baseline_hist = baseline_hist / baseline_hist.sum()
    current_hist = current_hist / current_hist.sum()
    
    # Compute symmetric KL divergence
    kl_forward = np.sum(kl_div(baseline_hist, current_hist))
    kl_backward = np.sum(kl_div(current_hist, baseline_hist))
    
    return (kl_forward + kl_backward) / 2.0


def compute_chi_square(baseline: np.ndarray, current: np.ndarray) -> float:
    """
    Compute chi-square statistic for categorical features
    
    Returns normalized chi-square statistic (0-1 range)
    """
    # Get value counts
    baseline_counts = pd.Series(baseline).value_counts()
    current_counts = pd.Series(current).value_counts()
    
    # Get all unique values
    all_values = set(baseline_counts.index) | set(current_counts.index)
    
    # Build contingency table
    contingency = []
    for val in all_values:
        contingency.append([
            baseline_counts.get(val, 0),
            current_counts.get(val, 0)
        ])
    
    contingency = np.array(contingency)
    
    # Compute chi-square test
    try:
        chi2, p_value, dof, expected = chi2_contingency(contingency)
        # Normalize by degrees of freedom
        return min(chi2 / (dof + 1), 1.0)
    except:
        return 0.0


def detect_prediction_drift(
    baseline_scores: pd.Series,
    current_scores: pd.Series,
    threshold: float
) -> Dict[str, Any]:
    """
    Detect prediction drift by comparing risk score distributions
    """
    # Compute KL divergence for predictions
    kl_score = compute_kl_divergence(
        baseline_scores.values,
        current_scores.values
    )
    
    # Compute percentage of predictions that shifted significantly
    baseline_high_risk = (baseline_scores > 0.5).mean()
    current_high_risk = (current_scores > 0.5).mean()
    drift_percentage = abs(current_high_risk - baseline_high_risk)
    
    return {
        'kl_divergence': kl_score,
        'drift_percentage': drift_percentage,
        'baseline_high_risk_pct': baseline_high_risk,
        'current_high_risk_pct': current_high_risk,
        'drifted': drift_percentage > threshold
    }


def publish_drift_metrics(drift_results: Dict[str, Any], prediction_drift: Dict[str, Any]):
    """Publish drift metrics to CloudWatch"""
    metrics = [
        {
            'MetricName': 'FeatureDriftCount',
            'Value': drift_results['drifted_feature_count'],
            'Unit': 'Count'
        },
        {
            'MetricName': 'AverageKLDivergence',
            'Value': np.mean(list(drift_results['feature_drift_scores'].values())) if drift_results['feature_drift_scores'] else 0,
            'Unit': 'None'
        }
    ]
    
    if prediction_drift:
        metrics.append({
            'MetricName': 'PredictionDriftPercentage',
            'Value': prediction_drift['drift_percentage'] * 100,
            'Unit': 'Percent'
        })
    
    cloudwatch_client.put_metric_data(
        Namespace='BitoGuard/MLPipeline',
        MetricData=metrics
    )
    
    logger.info(f"Published {len(metrics)} drift metrics to CloudWatch")


def send_drift_alert(
    drift_results: Dict[str, Any],
    prediction_drift: Dict[str, Any],
    bucket_name: str
):
    """Send SNS alert for significant drift"""
    topic_arn = os.environ.get('DRIFT_ALERTS_TOPIC_ARN')
    
    if not topic_arn:
        logger.warning("DRIFT_ALERTS_TOPIC_ARN not set, skipping alert")
        return
    
    # Build alert message
    message_lines = [
        "⚠️ Feature Drift Detected",
        "",
        f"Drifted Features: {drift_results['drifted_feature_count']} / {drift_results['total_features']}",
        ""
    ]
    
    # Add top drifted features
    if drift_results['drifted_features']:
        message_lines.append("Top Drifted Features:")
        for feat in drift_results['drifted_features'][:5]:
            message_lines.append(f"  • {feat['feature']}: {feat['drift_score']:.4f}")
        message_lines.append("")
    
    # Add prediction drift if available
    if prediction_drift and prediction_drift['drifted']:
        message_lines.extend([
            f"Prediction Drift: {prediction_drift['drift_percentage']*100:.2f}%",
            f"  Baseline High-Risk: {prediction_drift['baseline_high_risk_pct']*100:.2f}%",
            f"  Current High-Risk: {prediction_drift['current_high_risk_pct']*100:.2f}%",
            ""
        ])
    
    message_lines.append(f"Bucket: {bucket_name}")
    
    message = "\n".join(message_lines)
    
    sns_client.publish(
        TopicArn=topic_arn,
        Subject="BitoGuard ML Pipeline - Drift Alert",
        Message=message
    )
    
    logger.info("Sent drift alert to SNS")


def save_drift_report(
    drift_results: Dict[str, Any],
    prediction_drift: Dict[str, Any],
    bucket_name: str,
    snapshot_id: str
) -> str:
    """Save drift report to S3"""
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'snapshot_id': snapshot_id,
        'drift_results': drift_results,
        'prediction_drift': prediction_drift
    }
    
    # Build S3 key
    dt = datetime.utcnow()
    s3_key = f"drift-reports/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/drift_{snapshot_id}.json"
    
    # Upload to S3
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(report, indent=2),
        ContentType='application/json'
    )
    
    logger.info(f"Saved drift report to s3://{bucket_name}/{s3_key}")
    
    return f"s3://{bucket_name}/{s3_key}"
