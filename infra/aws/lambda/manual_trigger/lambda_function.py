"""
Manual Trigger Lambda Function

Allows manual triggering of the ML pipeline via API with custom parameters.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
stepfunctions_client = boto3.client('stepfunctions')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for manual pipeline triggering
    
    Expected event structure:
    {
        "execution_type": "full" | "incremental",
        "skip_training": false,
        "model_types": ["lgbm", "catboost", "iforest"]  # optional
    }
    """
    try:
        # Extract parameters
        execution_type = event.get('execution_type', 'full')
        skip_training = event.get('skip_training', False)
        model_types = event.get('model_types', ['lgbm', 'catboost', 'iforest'])
        
        # Validate execution type
        if execution_type not in ['full', 'incremental']:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f"Invalid execution_type: {execution_type}. Must be 'full' or 'incremental'"
                })
            }
        
        # Validate model types
        valid_model_types = {'lgbm', 'catboost', 'iforest'}
        invalid_types = set(model_types) - valid_model_types
        if invalid_types:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f"Invalid model_types: {invalid_types}. Must be subset of {valid_model_types}"
                })
            }
        
        logger.info(f"Starting manual pipeline execution: type={execution_type}, skip_training={skip_training}")
        
        # Get state machine ARN from environment
        state_machine_arn = os.environ.get('STATE_MACHINE_ARN')
        if not state_machine_arn:
            raise ValueError("STATE_MACHINE_ARN environment variable not set")
        
        # Build execution input
        execution_input = {
            'execution_type': execution_type,
            'skip_training': skip_training,
            'model_types': model_types,
            'triggered_by': 'manual',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Generate execution name
        execution_name = f"manual-{execution_type}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        # Start Step Functions execution
        response = stepfunctions_client.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_name,
            input=json.dumps(execution_input)
        )
        
        execution_arn = response['executionArn']
        start_date = response['startDate'].isoformat()
        
        logger.info(f"Started pipeline execution: {execution_arn}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Pipeline execution started successfully',
                'execution_arn': execution_arn,
                'execution_name': execution_name,
                'start_date': start_date,
                'execution_type': execution_type,
                'skip_training': skip_training
            })
        }
    
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"AWS API error: {str(e)}"
            })
        }
    
    except Exception as e:
        logger.error(f"Manual trigger failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
