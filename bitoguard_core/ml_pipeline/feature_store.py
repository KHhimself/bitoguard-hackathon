"""
Feature Store Service for BitoGuard ML Pipeline

Manages feature snapshot storage in S3 with Parquet format, date partitioning,
and metadata tracking. Integrates with existing feature engineering modules.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class FeatureSnapshot:
    """Represents a feature snapshot with metadata"""
    snapshot_id: str
    timestamp: datetime
    feature_count: int
    row_count: int
    feature_names: List[str]
    s3_path: str
    local_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FeatureSnapshot':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class FeatureStore:
    """
    Manages feature snapshots in S3 with Parquet format and date partitioning.
    
    Features:
    - Parquet export with Snappy compression
    - S3 upload with date partitioning (year=YYYY/month=MM/day=DD)
    - Feature metadata tracking
    - Snapshot versioning
    - Local caching
    """
    
    def __init__(
        self,
        bucket_name: str,
        prefix: str = "features",
        local_cache_dir: Optional[str] = None,
        region_name: str = "us-east-1"
    ):
        """
        Initialize feature store
        
        Args:
            bucket_name: S3 bucket name for feature storage
            prefix: S3 key prefix (default: "features")
            local_cache_dir: Local directory for caching (optional)
            region_name: AWS region
        """
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.local_cache_dir = Path(local_cache_dir) if local_cache_dir else None
        self.region_name = region_name
        
        # Initialize S3 client
        self.s3_client = boto3.client('s3', region_name=region_name)
        
        # Create local cache directory if specified
        if self.local_cache_dir:
            self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            f"Initialized FeatureStore: bucket={bucket_name}, "
            f"prefix={prefix}, region={region_name}"
        )
    
    def save_snapshot(
        self,
        df: pd.DataFrame,
        snapshot_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        partition_date: Optional[datetime] = None
    ) -> FeatureSnapshot:
        """
        Save feature snapshot to S3 with Parquet format
        
        Args:
            df: Feature DataFrame to save
            snapshot_id: Unique snapshot ID (auto-generated if None)
            metadata: Additional metadata to store
            partition_date: Date for partitioning (default: now)
        
        Returns:
            FeatureSnapshot object with metadata
        """
        # Generate snapshot ID if not provided
        if snapshot_id is None:
            snapshot_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        
        # Use current time for partitioning if not provided
        if partition_date is None:
            partition_date = datetime.utcnow()
        
        # Build S3 path with date partitioning
        s3_key = self._build_s3_key(snapshot_id, partition_date)
        
        # Save locally first (for caching and upload)
        local_path = None
        if self.local_cache_dir:
            local_path = self.local_cache_dir / f"{snapshot_id}.parquet"
            df.to_parquet(
                local_path,
                engine='pyarrow',
                compression='snappy',
                index=False
            )
            logger.info(f"Saved feature snapshot locally: {local_path}")
        
        # Upload to S3
        try:
            if local_path:
                self.s3_client.upload_file(
                    str(local_path),
                    self.bucket_name,
                    s3_key
                )
            else:
                # Direct upload without local caching
                parquet_buffer = df.to_parquet(
                    engine='pyarrow',
                    compression='snappy',
                    index=False
                )
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=parquet_buffer
                )
            
            logger.info(f"Uploaded feature snapshot to S3: s3://{self.bucket_name}/{s3_key}")
        
        except ClientError as e:
            logger.error(f"Failed to upload feature snapshot to S3: {e}")
            raise
        
        # Create snapshot metadata
        snapshot = FeatureSnapshot(
            snapshot_id=snapshot_id,
            timestamp=partition_date,
            feature_count=len(df.columns),
            row_count=len(df),
            feature_names=df.columns.tolist(),
            s3_path=f"s3://{self.bucket_name}/{s3_key}",
            local_path=str(local_path) if local_path else None,
            metadata=metadata or {}
        )
        
        # Save metadata JSON
        self._save_metadata(snapshot, partition_date)
        
        return snapshot
    
    def load_snapshot(
        self,
        snapshot_id: str,
        partition_date: Optional[datetime] = None,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Load feature snapshot from S3
        
        Args:
            snapshot_id: Snapshot ID to load
            partition_date: Date partition (required if not using cache)
            use_cache: Use local cache if available
        
        Returns:
            Feature DataFrame
        """
        # Check local cache first
        if use_cache and self.local_cache_dir:
            local_path = self.local_cache_dir / f"{snapshot_id}.parquet"
            if local_path.exists():
                logger.info(f"Loading feature snapshot from cache: {local_path}")
                return pd.read_parquet(local_path, engine='pyarrow')
        
        # Download from S3
        if partition_date is None:
            raise ValueError("partition_date required when loading from S3 without cache")
        
        s3_key = self._build_s3_key(snapshot_id, partition_date)
        
        try:
            # Download to local cache if enabled
            if self.local_cache_dir:
                local_path = self.local_cache_dir / f"{snapshot_id}.parquet"
                self.s3_client.download_file(
                    self.bucket_name,
                    s3_key,
                    str(local_path)
                )
                logger.info(f"Downloaded feature snapshot from S3: {s3_key}")
                return pd.read_parquet(local_path, engine='pyarrow')
            else:
                # Direct download without caching
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
                return pd.read_parquet(response['Body'], engine='pyarrow')
        
        except ClientError as e:
            logger.error(f"Failed to load feature snapshot from S3: {e}")
            raise
    
    def get_latest_snapshot(self) -> Optional[FeatureSnapshot]:
        """
        Get metadata for the most recent feature snapshot
        
        Returns:
            FeatureSnapshot object or None if no snapshots exist
        """
        try:
            # List all metadata files
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"{self.prefix}/metadata/",
                MaxKeys=1000
            )
            
            if 'Contents' not in response:
                return None
            
            # Find most recent metadata file
            metadata_files = [
                obj['Key'] for obj in response['Contents']
                if obj['Key'].endswith('.json')
            ]
            
            if not metadata_files:
                return None
            
            # Sort by key (which includes timestamp) and get latest
            latest_key = sorted(metadata_files)[-1]
            
            # Load metadata
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=latest_key
            )
            metadata_json = json.loads(response['Body'].read())
            
            return FeatureSnapshot.from_dict(metadata_json)
        
        except ClientError as e:
            logger.error(f"Failed to get latest snapshot: {e}")
            return None
    
    def list_snapshots(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[FeatureSnapshot]:
        """
        List feature snapshots within date range
        
        Args:
            start_date: Start date filter (inclusive)
            end_date: End date filter (inclusive)
            limit: Maximum number of snapshots to return
        
        Returns:
            List of FeatureSnapshot objects
        """
        snapshots = []
        
        try:
            # List metadata files
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=f"{self.prefix}/metadata/"
            )
            
            for page in pages:
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    if not obj['Key'].endswith('.json'):
                        continue
                    
                    # Load metadata
                    response = self.s3_client.get_object(
                        Bucket=self.bucket_name,
                        Key=obj['Key']
                    )
                    metadata_json = json.loads(response['Body'].read())
                    snapshot = FeatureSnapshot.from_dict(metadata_json)
                    
                    # Apply date filters
                    if start_date and snapshot.timestamp < start_date:
                        continue
                    if end_date and snapshot.timestamp > end_date:
                        continue
                    
                    snapshots.append(snapshot)
                    
                    if len(snapshots) >= limit:
                        break
                
                if len(snapshots) >= limit:
                    break
            
            # Sort by timestamp descending
            snapshots.sort(key=lambda s: s.timestamp, reverse=True)
            
            return snapshots[:limit]
        
        except ClientError as e:
            logger.error(f"Failed to list snapshots: {e}")
            return []
    
    def _build_s3_key(self, snapshot_id: str, partition_date: datetime) -> str:
        """Build S3 key with date partitioning"""
        year = partition_date.strftime("%Y")
        month = partition_date.strftime("%m")
        day = partition_date.strftime("%d")
        
        return f"{self.prefix}/year={year}/month={month}/day={day}/{snapshot_id}.parquet"
    
    def _save_metadata(self, snapshot: FeatureSnapshot, partition_date: datetime):
        """Save snapshot metadata to S3"""
        metadata_key = self._build_metadata_key(snapshot.snapshot_id, partition_date)
        metadata_json = json.dumps(snapshot.to_dict(), indent=2)
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=metadata_key,
                Body=metadata_json.encode('utf-8'),
                ContentType='application/json'
            )
            logger.info(f"Saved snapshot metadata: s3://{self.bucket_name}/{metadata_key}")
        
        except ClientError as e:
            logger.error(f"Failed to save snapshot metadata: {e}")
            # Don't raise - metadata is supplementary
    
    def _build_metadata_key(self, snapshot_id: str, partition_date: datetime) -> str:
        """Build S3 key for metadata file"""
        year = partition_date.strftime("%Y")
        month = partition_date.strftime("%m")
        day = partition_date.strftime("%d")
        
        return f"{self.prefix}/metadata/year={year}/month={month}/day={day}/{snapshot_id}.json"
