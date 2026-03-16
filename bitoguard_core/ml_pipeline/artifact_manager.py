"""Model artifact manager for S3-based model registry."""
import json
import gzip
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import boto3
from botocore.exceptions import ClientError


@dataclass
class ModelArtifact:
    """Metadata for a trained model artifact."""
    model_version: str
    model_type: str
    created_at: str
    s3_uri: str
    artifact_size_bytes: int
    storage_class: str = "STANDARD"
    status: str = "active"
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ModelRegistry:
    """Registry of all model versions for a model type."""
    model_type: str
    latest_version: str
    versions: List[ModelArtifact]
    
    def get_latest(self) -> ModelArtifact:
        """Get the latest active model."""
        return next(v for v in self.versions if v.model_version == self.latest_version)
    
    def get_version(self, version: str) -> Optional[ModelArtifact]:
        """Get a specific model version."""
        return next((v for v in self.versions if v.model_version == version), None)


class ArtifactManager:
    """Manages model artifacts in S3."""
    
    def __init__(self, bucket: str, region: str = 'us-west-2'):
        """
        Initialize artifact manager.
        
        Args:
            bucket: S3 bucket name
            region: AWS region
        """
        self.bucket = bucket
        self.region = region
        self.s3 = boto3.client('s3', region_name=region)
        self.models_prefix = "models/"
    
    def upload_model(
        self,
        model_type: str,
        local_path: Path,
        metadata: Dict[str, Any],
        compress: bool = True
    ) -> ModelArtifact:
        """
        Upload model artifact to S3 with versioning and metadata.
        
        Args:
            model_type: Model type (lgbm, catboost, iforest)
            local_path: Local path to model file
            metadata: Model metadata dictionary
            compress: Whether to gzip compress before upload
            
        Returns:
            ModelArtifact with upload details
        """
        # Generate version
        version = f"{model_type}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        
        # S3 key structure: models/{model_type}/{version}/
        s3_key_prefix = f"{self.models_prefix}{model_type}/{version}/"
        
        # Upload model file
        model_filename = local_path.name
        if compress and not model_filename.endswith('.gz'):
            # Compress file
            compressed_data = self._compress_file(local_path)
            s3_key = f"{s3_key_prefix}{model_filename}.gz"
            self.s3.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=compressed_data,
                ContentEncoding='gzip'
            )
            artifact_size = len(compressed_data)
        else:
            # Upload without compression
            s3_key = f"{s3_key_prefix}{model_filename}"
            with open(local_path, 'rb') as f:
                file_data = f.read()
                self.s3.put_object(
                    Bucket=self.bucket,
                    Key=s3_key,
                    Body=file_data
                )
                artifact_size = len(file_data)
        
        # Upload metadata
        metadata_key = f"{s3_key_prefix}metadata.json"
        metadata_with_version = {
            **metadata,
            "model_version": version,
            "model_type": model_type,
            "created_at": datetime.utcnow().isoformat()
        }
        self.s3.put_object(
            Bucket=self.bucket,
            Key=metadata_key,
            Body=json.dumps(metadata_with_version, indent=2),
            ContentType='application/json'
        )
        
        # Update manifest
        self._update_manifest(model_type, version)
        
        # Create artifact object
        artifact = ModelArtifact(
            model_version=version,
            model_type=model_type,
            created_at=datetime.utcnow().isoformat(),
            s3_uri=f"s3://{self.bucket}/{s3_key_prefix}",
            artifact_size_bytes=artifact_size,
            storage_class="STANDARD",
            status="active",
            metadata=metadata_with_version
        )
        
        return artifact
    
    def download_model(
        self,
        model_type: str,
        version: str,
        local_path: Path
    ) -> Path:
        """
        Download model artifact from S3.
        
        Args:
            model_type: Model type
            version: Model version
            local_path: Local directory to save model
            
        Returns:
            Path to downloaded model file
        """
        s3_prefix = f"{self.models_prefix}{model_type}/{version}/"
        
        # List objects in version directory
        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=s3_prefix
        )
        
        if 'Contents' not in response:
            raise FileNotFoundError(f"No artifacts found for {model_type} version {version}")
        
        # Download all files
        local_path.mkdir(parents=True, exist_ok=True)
        
        for obj in response['Contents']:
            key = obj['Key']
            filename = key.split('/')[-1]
            
            if filename:  # Skip directory markers
                local_file = local_path / filename
                self.s3.download_file(self.bucket, key, str(local_file))
                
                # Decompress if gzipped
                if filename.endswith('.gz'):
                    decompressed_file = local_path / filename[:-3]
                    with gzip.open(local_file, 'rb') as f_in:
                        with open(decompressed_file, 'wb') as f_out:
                            f_out.write(f_in.read())
                    local_file.unlink()  # Remove compressed file
                    return decompressed_file
        
        return local_path
    
    def get_latest_version(self, model_type: str) -> str:
        """
        Get the latest version for a model type.
        
        Args:
            model_type: Model type
            
        Returns:
            Latest version string
        """
        manifest = self._load_manifest(model_type)
        return manifest['latest_version']
    
    def get_registry(self, model_type: str) -> ModelRegistry:
        """
        Get complete registry for a model type.
        
        Args:
            model_type: Model type
            
        Returns:
            ModelRegistry with all versions
        """
        manifest = self._load_manifest(model_type)
        
        artifacts = []
        for version_info in manifest['versions']:
            artifact = ModelArtifact(**version_info)
            artifacts.append(artifact)
        
        return ModelRegistry(
            model_type=model_type,
            latest_version=manifest['latest_version'],
            versions=artifacts
        )
    
    def _compress_file(self, file_path: Path) -> bytes:
        """Compress file with gzip."""
        with open(file_path, 'rb') as f_in:
            return gzip.compress(f_in.read())
    
    def _load_manifest(self, model_type: str) -> Dict[str, Any]:
        """Load manifest file for model type."""
        manifest_key = f"{self.models_prefix}{model_type}/manifest.json"
        
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=manifest_key)
            return json.loads(response['Body'].read())
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                # Create new manifest
                return {
                    "model_type": model_type,
                    "latest_version": "",
                    "versions": []
                }
            raise
    
    def _update_manifest(self, model_type: str, new_version: str):
        """Update manifest with new version."""
        manifest = self._load_manifest(model_type)
        
        # Add new version
        manifest['latest_version'] = new_version
        manifest['versions'].insert(0, {
            "model_version": new_version,
            "model_type": model_type,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active",
            "storage_class": "STANDARD",
            "s3_uri": f"s3://{self.bucket}/{self.models_prefix}{model_type}/{new_version}/",
            "artifact_size_bytes": 0  # Will be updated later if needed
        })
        
        # Save manifest
        manifest_key = f"{self.models_prefix}{model_type}/manifest.json"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, indent=2),
            ContentType='application/json'
        )
