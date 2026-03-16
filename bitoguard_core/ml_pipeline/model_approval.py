"""
Model approval workflow for SageMaker Model Registry.

This module provides functions for approving, rejecting, and retrieving
models from the SageMaker Model Registry.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ModelApprovalWorkflow:
    """Manages model approval workflow in SageMaker Model Registry."""
    
    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize model approval workflow.
        
        Args:
            region_name: AWS region name
        """
        self.sagemaker = boto3.client('sagemaker', region_name=region_name)
        self.region_name = region_name
        
        logger.info(f"Initialized ModelApprovalWorkflow in region: {region_name}")
    
    def approve_model(
        self,
        model_package_arn: str,
        approval_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a model for deployment.
        
        Args:
            model_package_arn: ARN of the model package to approve
            approval_description: Optional description for approval
            
        Returns:
            Dictionary with approval details
        """
        logger.info(f"Approving model: {model_package_arn}")
        
        try:
            # Update model package approval status
            response = self.sagemaker.update_model_package(
                ModelPackageArn=model_package_arn,
                ModelApprovalStatus='Approved',
                ApprovalDescription=approval_description or f"Approved on {datetime.utcnow().isoformat()}"
            )
            
            logger.info(f"Model approved successfully: {model_package_arn}")
            
            return {
                'model_package_arn': response['ModelPackageArn'],
                'approval_status': 'Approved',
                'approval_timestamp': datetime.utcnow().isoformat()
            }
            
        except ClientError as e:
            logger.error(f"Error approving model: {e}")
            raise
    
    def reject_model(
        self,
        model_package_arn: str,
        rejection_reason: str
    ) -> Dict[str, Any]:
        """
        Reject a model.
        
        Args:
            model_package_arn: ARN of the model package to reject
            rejection_reason: Reason for rejection
            
        Returns:
            Dictionary with rejection details
        """
        logger.info(f"Rejecting model: {model_package_arn}")
        
        try:
            response = self.sagemaker.update_model_package(
                ModelPackageArn=model_package_arn,
                ModelApprovalStatus='Rejected',
                ApprovalDescription=rejection_reason
            )
            
            logger.info(f"Model rejected: {model_package_arn}")
            
            return {
                'model_package_arn': response['ModelPackageArn'],
                'approval_status': 'Rejected',
                'rejection_reason': rejection_reason,
                'rejection_timestamp': datetime.utcnow().isoformat()
            }
            
        except ClientError as e:
            logger.error(f"Error rejecting model: {e}")
            raise
    
    def get_approved_model(
        self,
        model_package_group_name: str,
        model_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the latest approved model from a model package group.
        
        Args:
            model_package_group_name: Name of the model package group
            model_type: Optional model type filter
            
        Returns:
            Dictionary with model details or None if no approved model found
        """
        logger.info(f"Retrieving latest approved model from: {model_package_group_name}")
        
        try:
            # List model packages in the group
            response = self.sagemaker.list_model_packages(
                ModelPackageGroupName=model_package_group_name,
                ModelApprovalStatus='Approved',
                SortBy='CreationTime',
                SortOrder='Descending',
                MaxResults=1
            )
            
            if not response.get('ModelPackageSummaryList'):
                logger.warning(f"No approved models found in {model_package_group_name}")
                return None
            
            # Get the latest approved model
            latest_model = response['ModelPackageSummaryList'][0]
            model_package_arn = latest_model['ModelPackageArn']
            
            # Get detailed information
            model_details = self.sagemaker.describe_model_package(
                ModelPackageName=model_package_arn
            )
            
            result = {
                'model_package_arn': model_package_arn,
                'model_package_group_name': model_package_group_name,
                'model_package_version': latest_model.get('ModelPackageVersion'),
                'creation_time': latest_model['CreationTime'].isoformat(),
                'approval_status': latest_model['ModelApprovalStatus'],
                'model_data_url': None,
                'inference_image_uri': None,
                'customer_metadata': model_details.get('CustomerMetadataProperties', {})
            }
            
            # Extract model data URL and inference image
            if 'InferenceSpecification' in model_details:
                containers = model_details['InferenceSpecification'].get('Containers', [])
                if containers:
                    result['model_data_url'] = containers[0].get('ModelDataUrl')
                    result['inference_image_uri'] = containers[0].get('Image')
            
            logger.info(f"Found approved model: {model_package_arn}")
            
            return result
            
        except ClientError as e:
            logger.error(f"Error retrieving approved model: {e}")
            raise
    
    def list_pending_approvals(
        self,
        model_package_group_name: Optional[str] = None,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List models pending approval.
        
        Args:
            model_package_group_name: Optional model package group name filter
            max_results: Maximum number of results to return
            
        Returns:
            List of model packages pending approval
        """
        logger.info("Listing models pending approval")
        
        try:
            params = {
                'ModelApprovalStatus': 'PendingManualApproval',
                'SortBy': 'CreationTime',
                'SortOrder': 'Descending',
                'MaxResults': min(max_results, 100)
            }
            
            if model_package_group_name:
                params['ModelPackageGroupName'] = model_package_group_name
            
            response = self.sagemaker.list_model_packages(**params)
            
            pending_models = []
            for model in response.get('ModelPackageSummaryList', []):
                pending_models.append({
                    'model_package_arn': model['ModelPackageArn'],
                    'model_package_group_name': model['ModelPackageGroupName'],
                    'model_package_version': model.get('ModelPackageVersion'),
                    'creation_time': model['CreationTime'].isoformat(),
                    'approval_status': model['ModelApprovalStatus']
                })
            
            logger.info(f"Found {len(pending_models)} models pending approval")
            
            return pending_models
            
        except ClientError as e:
            logger.error(f"Error listing pending approvals: {e}")
            raise
    
    def get_model_details(self, model_package_arn: str) -> Dict[str, Any]:
        """
        Get detailed information about a model package.
        
        Args:
            model_package_arn: ARN of the model package
            
        Returns:
            Dictionary with model details
        """
        logger.info(f"Retrieving model details: {model_package_arn}")
        
        try:
            response = self.sagemaker.describe_model_package(
                ModelPackageName=model_package_arn
            )
            
            details = {
                'model_package_arn': response['ModelPackageArn'],
                'model_package_name': response.get('ModelPackageName'),
                'model_package_group_name': response.get('ModelPackageGroupName'),
                'model_package_version': response.get('ModelPackageVersion'),
                'model_package_description': response.get('ModelPackageDescription'),
                'creation_time': response['CreationTime'].isoformat(),
                'approval_status': response['ModelApprovalStatus'],
                'approval_description': response.get('ApprovalDescription'),
                'customer_metadata': response.get('CustomerMetadataProperties', {}),
                'model_metrics': response.get('ModelMetrics', {}),
                'inference_specification': response.get('InferenceSpecification', {})
            }
            
            return details
            
        except ClientError as e:
            logger.error(f"Error retrieving model details: {e}")
            raise


# Convenience functions
def approve_model(model_package_arn: str, approval_description: Optional[str] = None) -> Dict[str, Any]:
    """
    Approve a model for deployment.
    
    Args:
        model_package_arn: ARN of the model package to approve
        approval_description: Optional description for approval
        
    Returns:
        Dictionary with approval details
    """
    workflow = ModelApprovalWorkflow()
    return workflow.approve_model(model_package_arn, approval_description)


def get_approved_model(model_package_group_name: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest approved model from a model package group.
    
    Args:
        model_package_group_name: Name of the model package group
        
    Returns:
        Dictionary with model details or None if no approved model found
    """
    workflow = ModelApprovalWorkflow()
    return workflow.get_approved_model(model_package_group_name)


def list_pending_approvals(model_package_group_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List models pending approval.
    
    Args:
        model_package_group_name: Optional model package group name filter
        
    Returns:
        List of model packages pending approval
    """
    workflow = ModelApprovalWorkflow()
    return workflow.list_pending_approvals(model_package_group_name)
