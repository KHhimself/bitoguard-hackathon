"""
Configuration loader for ML Pipeline.

Loads configuration from AWS Systems Manager Parameter Store with caching.
"""
import os
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError


class PipelineConfig:
    """Configuration manager for ML Pipeline."""
    
    def __init__(self, region: Optional[str] = None):
        """
        Initialize configuration loader.
        
        Args:
            region: AWS region. If None, uses AWS_DEFAULT_REGION env var or us-west-2
        """
        self.region = region or os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
        self.ssm = boto3.client('ssm', region_name=self.region)
        self._cache: Dict[str, str] = {}
        self.parameter_prefix = "/bitoguard/ml-pipeline/"
    
    def get_parameter(self, name: str, default: Any = None) -> str:
        """
        Get parameter from SSM Parameter Store with caching.
        
        Args:
            name: Parameter name (without prefix)
            default: Default value if parameter not found
            
        Returns:
            Parameter value as string
            
        Raises:
            ValueError: If parameter not found and no default provided
        """
        # Add prefix if not already present
        if not name.startswith(self.parameter_prefix):
            full_name = f"{self.parameter_prefix}{name}"
        else:
            full_name = name
        
        # Check cache
        if full_name in self._cache:
            return self._cache[full_name]
        
        try:
            response = self.ssm.get_parameter(Name=full_name, WithDecryption=True)
            value = response['Parameter']['Value']
            self._cache[full_name] = value
            return value
        except ClientError as e:
            if e.response['Error']['Code'] == 'ParameterNotFound':
                if default is not None:
                    return str(default)
                raise ValueError(f"Parameter {full_name} not found and no default provided")
            raise
    
    def get_training_config(self, model_type: str) -> Dict[str, Any]:
        """
        Get training hyperparameters for a model type.
        
        Args:
            model_type: Model type (lgbm, catboost, iforest)
            
        Returns:
            Dictionary of hyperparameters with proper types
        """
        prefix = f"training/{model_type}/"
        
        try:
            # Get all parameters with prefix
            response = self.ssm.get_parameters_by_path(
                Path=f"{self.parameter_prefix}{prefix}",
                Recursive=True,
                WithDecryption=True
            )
            
            config = {}
            for param in response['Parameters']:
                # Extract key from full parameter name
                key = param['Name'].replace(f"{self.parameter_prefix}{prefix}", '')
                value = param['Value']
                
                # Type conversion
                try:
                    if '.' in value:
                        config[key] = float(value)
                    else:
                        config[key] = int(value)
                except ValueError:
                    config[key] = value
            
            return config
        except ClientError as e:
            raise ValueError(f"Failed to load training config for {model_type}: {e}")
    
    def get_scoring_config(self) -> Dict[str, float]:
        """
        Get scoring thresholds.
        
        Returns:
            Dictionary with alert_threshold, high_risk_threshold, critical_risk_threshold
        """
        return {
            'alert_threshold': float(self.get_parameter('scoring/alert_threshold', '80')),
            'high_risk_threshold': float(self.get_parameter('scoring/high_risk_threshold', '60')),
            'critical_risk_threshold': float(self.get_parameter('scoring/critical_risk_threshold', '80'))
        }
    
    def get_drift_config(self) -> Dict[str, float]:
        """
        Get drift detection thresholds.
        
        Returns:
            Dictionary with kl_threshold and prediction_threshold
        """
        return {
            'kl_threshold': float(self.get_parameter('drift/kl_threshold', '0.1')),
            'prediction_threshold': float(self.get_parameter('drift/prediction_threshold', '15'))
        }
    
    def get_resource_config(self, stage: str) -> Dict[str, int]:
        """
        Get resource allocation for a pipeline stage.
        
        Args:
            stage: Pipeline stage (sync, features, scoring)
            
        Returns:
            Dictionary with cpu and memory values
        """
        return {
            'cpu': int(self.get_parameter(f'resources/{stage}/cpu', '1024')),
            'memory': int(self.get_parameter(f'resources/{stage}/memory', '2048'))
        }
    
    def get_s3_config(self) -> Dict[str, str]:
        """
        Get S3 configuration.
        
        Returns:
            Dictionary with bucket and prefix paths
        """
        return {
            'bucket': self.get_parameter('s3/bucket'),
            'models_prefix': self.get_parameter('s3/models_prefix', 'models/'),
            'features_prefix': self.get_parameter('s3/features_prefix', 'features/'),
            'drift_prefix': self.get_parameter('s3/drift_prefix', 'drift_reports/')
        }
    
    def get_schedule_config(self) -> Dict[str, str]:
        """
        Get scheduling configuration.
        
        Returns:
            Dictionary with daily_full and incremental cron expressions
        """
        return {
            'daily_full': self.get_parameter('schedule/daily-full', 'cron(0 2 * * ? *)'),
            'incremental': self.get_parameter('schedule/incremental', 'cron(0 8,12,16,20 * * ? *)')
        }
    
    def validate_config(self) -> bool:
        """
        Validate all required parameters exist and have valid values.
        
        Returns:
            True if configuration is valid
            
        Raises:
            ValueError: If configuration is invalid with details
        """
        errors = []
        
        # Required parameters
        required_params = [
            's3/bucket',
            'scoring/alert_threshold',
            'notifications/sns_topic'
        ]
        
        for param in required_params:
            try:
                value = self.get_parameter(param)
                if not value:
                    errors.append(f"Parameter {param} is empty")
            except ValueError as e:
                errors.append(str(e))
        
        # Validate threshold ranges
        try:
            scoring_config = self.get_scoring_config()
            for key, value in scoring_config.items():
                if not (0 <= value <= 100):
                    errors.append(f"Scoring threshold {key}={value} must be between 0 and 100")
        except Exception as e:
            errors.append(f"Failed to validate scoring config: {e}")
        
        try:
            drift_config = self.get_drift_config()
            if not (0 <= drift_config['kl_threshold'] <= 1):
                errors.append(f"KL divergence threshold must be between 0 and 1")
            if not (0 <= drift_config['prediction_threshold'] <= 100):
                errors.append(f"Prediction drift threshold must be between 0 and 100")
        except Exception as e:
            errors.append(f"Failed to validate drift config: {e}")
        
        # Validate resource configs
        for stage in ['sync', 'features', 'scoring']:
            try:
                resource_config = self.get_resource_config(stage)
                if resource_config['cpu'] < 256:
                    errors.append(f"CPU for {stage} must be at least 256")
                if resource_config['memory'] < 512:
                    errors.append(f"Memory for {stage} must be at least 512")
            except Exception as e:
                errors.append(f"Failed to validate resource config for {stage}: {e}")
        
        if errors:
            raise ValueError(f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return True
    
    def clear_cache(self):
        """Clear the parameter cache."""
        self._cache.clear()
    
    def log_active_config(self) -> Dict[str, Any]:
        """
        Get all active configuration for logging.
        
        Returns:
            Dictionary with all configuration values
        """
        return {
            'training': {
                'lgbm': self.get_training_config('lgbm'),
                'catboost': self.get_training_config('catboost'),
                'iforest': self.get_training_config('iforest')
            },
            'scoring': self.get_scoring_config(),
            'drift': self.get_drift_config(),
            'resources': {
                'sync': self.get_resource_config('sync'),
                'features': self.get_resource_config('features'),
                'scoring': self.get_resource_config('scoring')
            },
            's3': self.get_s3_config(),
            'schedule': self.get_schedule_config()
        }


# Singleton instance
_config_instance: Optional[PipelineConfig] = None


def get_config(region: Optional[str] = None) -> PipelineConfig:
    """
    Get singleton configuration instance.
    
    Args:
        region: AWS region (only used on first call)
        
    Returns:
        PipelineConfig instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = PipelineConfig(region=region)
    return _config_instance
