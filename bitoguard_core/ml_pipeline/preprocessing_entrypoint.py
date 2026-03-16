"""
SageMaker Processing Job Entry Point

This script is executed by SageMaker Processing Jobs to perform data preprocessing
and feature engineering. It integrates with existing feature engineering modules
and generates data quality reports.
"""
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, '/opt/ml/code')

from config import load_settings
from db.store import DuckDBStore
from features.registry import build_and_store_v2_features
from ml_pipeline.feature_store import FeatureStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_data_quality_report(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate comprehensive data quality metrics.
    
    Args:
        df: Feature DataFrame to analyze
        
    Returns:
        Dictionary containing quality metrics
    """
    logger.info("Generating data quality report...")
    
    # Basic statistics
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "row_count": len(df),
        "column_count": len(df.columns),
        "memory_usage_mb": float(df.memory_usage(deep=True).sum() / 1024 / 1024),
        "duplicate_rows": int(df.duplicated().sum()),
        "feature_completeness": float(1 - df.isnull().mean().mean())
    }
    
    # Null percentages for all columns
    null_percentages = df.isnull().mean()
    report["null_percentages"] = {
        col: float(pct) for col, pct in null_percentages.items()
    }
    
    # High null columns (>10%)
    report["high_null_columns"] = [
        col for col, pct in null_percentages.items() if pct > 0.1
    ]
    
    # Numeric feature statistics
    numeric_cols = df.select_dtypes(include=['number']).columns
    report["numeric_features"] = {}
    
    for col in numeric_cols:
        col_data = df[col].dropna()
        if len(col_data) == 0:
            continue
            
        mean_val = float(col_data.mean())
        std_val = float(col_data.std())
        
        # Detect outliers (3 standard deviations)
        outlier_mask = (col_data - mean_val).abs() > 3 * std_val
        outlier_count = int(outlier_mask.sum())
        
        report["numeric_features"][col] = {
            "mean": mean_val,
            "std": std_val,
            "min": float(col_data.min()),
            "max": float(col_data.max()),
            "median": float(col_data.median()),
            "outliers": outlier_count,
            "outlier_percentage": float(outlier_count / len(col_data))
        }
    
    # Categorical feature statistics
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    report["categorical_features"] = {}
    
    for col in categorical_cols:
        col_data = df[col].dropna()
        if len(col_data) == 0:
            continue
            
        value_counts = col_data.value_counts()
        report["categorical_features"][col] = {
            "unique_values": int(col_data.nunique()),
            "most_common": str(value_counts.index[0]) if len(value_counts) > 0 else None,
            "most_common_count": int(value_counts.iloc[0]) if len(value_counts) > 0 else 0
        }
    
    # Feature distributions summary
    report["feature_distributions"] = {
        "numeric_count": len(numeric_cols),
        "categorical_count": len(categorical_cols),
        "total_features": len(df.columns)
    }
    
    logger.info(f"Quality report generated: {report['row_count']} rows, "
                f"{report['column_count']} columns, "
                f"{report['feature_completeness']:.2%} completeness")
    
    return report


def load_data_from_efs(efs_path: str = "/opt/ml/artifacts") -> pd.DataFrame:
    """
    Load data from DuckDB on EFS.
    
    Args:
        efs_path: Path to EFS mount point
        
    Returns:
        Feature DataFrame
    """
    logger.info(f"Loading data from EFS: {efs_path}")
    
    # Use DuckDB from EFS
    db_path = Path(efs_path) / "bitoguard.duckdb"
    
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB file not found: {db_path}")
    
    logger.info(f"Using DuckDB: {db_path}")
    store = DuckDBStore(str(db_path))
    
    # Load canonical tables
    logger.info("Loading canonical tables...")
    users = store.read_table("canonical.users")
    fiat = store.read_table("canonical.fiat_transactions")
    crypto = store.read_table("canonical.crypto_transactions")
    trades = store.read_table("canonical.trade_orders")
    logins = store.read_table("canonical.login_events")
    edges = store.read_table("canonical.entity_edges")
    
    logger.info(f"Loaded tables: users={len(users)}, fiat={len(fiat)}, "
                f"crypto={len(crypto)}, trades={len(trades)}, "
                f"logins={len(logins)}, edges={len(edges)}")
    
    # Build features using existing feature engineering
    logger.info("Building features using registry...")
    features_df = build_and_store_v2_features(
        users, fiat, crypto, trades, logins, edges, store=store
    )
    
    logger.info(f"Generated {len(features_df)} rows with {len(features_df.columns)} features")
    
    return features_df


def load_data_from_s3(s3_uri: str) -> pd.DataFrame:
    """
    Load data from S3 (alternative to EFS).
    
    Args:
        s3_uri: S3 URI to raw data
        
    Returns:
        Feature DataFrame
    """
    logger.info(f"Loading data from S3: {s3_uri}")
    
    # Parse S3 URI
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    
    # Load from S3 using pandas
    df = pd.read_parquet(s3_uri, engine='pyarrow')
    
    logger.info(f"Loaded {len(df)} rows from S3")
    
    return df


def save_features_to_parquet(
    df: pd.DataFrame,
    output_path: Path,
    filename: str = "features.parquet"
) -> Path:
    """
    Save features to Parquet format with Snappy compression.
    
    Args:
        df: Feature DataFrame
        output_path: Output directory path
        filename: Output filename
        
    Returns:
        Path to saved file
    """
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / filename
    
    logger.info(f"Saving features to {output_file}...")
    
    df.to_parquet(
        output_file,
        engine='pyarrow',
        compression='snappy',
        index=False
    )
    
    file_size_mb = output_file.stat().st_size / 1024 / 1024
    logger.info(f"Saved {len(df)} rows to {output_file} ({file_size_mb:.2f} MB)")
    
    return output_file


def save_quality_report(
    report: Dict[str, Any],
    reports_path: Path,
    filename: str = "data_quality_report.json"
) -> Path:
    """
    Save data quality report to JSON.
    
    Args:
        report: Quality report dictionary
        reports_path: Reports directory path
        filename: Report filename
        
    Returns:
        Path to saved report
    """
    reports_path.mkdir(parents=True, exist_ok=True)
    report_file = reports_path / filename
    
    logger.info(f"Saving quality report to {report_file}...")
    
    report_file.write_text(json.dumps(report, indent=2))
    
    logger.info(f"Saved quality report to {report_file}")
    
    return report_file


def upload_to_feature_store(
    df: pd.DataFrame,
    bucket_name: Optional[str] = None,
    snapshot_id: Optional[str] = None
) -> None:
    """
    Upload features to S3 feature store (optional).
    
    Args:
        df: Feature DataFrame
        bucket_name: S3 bucket name
        snapshot_id: Snapshot ID
    """
    if not bucket_name:
        logger.info("Skipping feature store upload (no bucket specified)")
        return
    
    logger.info(f"Uploading to feature store: {bucket_name}")
    
    try:
        feature_store = FeatureStore(
            bucket_name=bucket_name,
            prefix="features/processed"
        )
        
        snapshot = feature_store.save_snapshot(
            df=df,
            snapshot_id=snapshot_id,
            metadata={
                "source": "sagemaker_processing",
                "processing_job": os.environ.get("PROCESSING_JOB_NAME", "unknown")
            }
        )
        
        logger.info(f"Uploaded snapshot: {snapshot.snapshot_id} to {snapshot.s3_path}")
        
    except Exception as e:
        logger.warning(f"Failed to upload to feature store: {e}")
        # Don't fail the job if feature store upload fails


def main():
    """Main processing entry point."""
    print("=" * 80)
    print("BitoGuard SageMaker Processing Job")
    print("=" * 80)
    print(f"Start Time: {datetime.utcnow().isoformat()}")
    print("=" * 80)
    
    # SageMaker paths
    input_path = Path("/opt/ml/processing/input")
    output_path = Path("/opt/ml/processing/output")
    reports_path = Path("/opt/ml/processing/reports")
    efs_path = Path("/opt/ml/artifacts")
    
    # Environment variables
    data_source = os.environ.get("DATA_SOURCE", "efs")  # "efs" or "s3"
    s3_input_uri = os.environ.get("S3_INPUT_URI", "")
    feature_store_bucket = os.environ.get("FEATURE_STORE_BUCKET", "")
    snapshot_id = os.environ.get("SNAPSHOT_ID", datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"))
    
    logger.info(f"Configuration:")
    logger.info(f"  Data Source: {data_source}")
    logger.info(f"  S3 Input URI: {s3_input_uri or 'N/A'}")
    logger.info(f"  Feature Store Bucket: {feature_store_bucket or 'N/A'}")
    logger.info(f"  Snapshot ID: {snapshot_id}")
    
    try:
        # Load data
        print(f"\n{'=' * 80}")
        print("Loading Data")
        print(f"{'=' * 80}\n")
        
        if data_source == "s3" and s3_input_uri:
            features_df = load_data_from_s3(s3_input_uri)
        else:
            # Default to EFS
            features_df = load_data_from_efs(str(efs_path))
        
        # Generate data quality report
        print(f"\n{'=' * 80}")
        print("Generating Data Quality Report")
        print(f"{'=' * 80}\n")
        
        quality_report = generate_data_quality_report(features_df)
        
        # Save processed features
        print(f"\n{'=' * 80}")
        print("Saving Processed Features")
        print(f"{'=' * 80}\n")
        
        output_file = save_features_to_parquet(features_df, output_path)
        
        # Save quality report
        print(f"\n{'=' * 80}")
        print("Saving Quality Report")
        print(f"{'=' * 80}\n")
        
        report_file = save_quality_report(quality_report, reports_path)
        
        # Upload to feature store (optional)
        if feature_store_bucket:
            print(f"\n{'=' * 80}")
            print("Uploading to Feature Store")
            print(f"{'=' * 80}\n")
            
            upload_to_feature_store(
                features_df,
                bucket_name=feature_store_bucket,
                snapshot_id=snapshot_id
            )
        
        # Print summary
        print(f"\n{'=' * 80}")
        print("Processing Summary")
        print(f"{'=' * 80}")
        print(f"Rows Processed: {len(features_df):,}")
        print(f"Features Generated: {len(features_df.columns)}")
        print(f"Feature Completeness: {quality_report['feature_completeness']:.2%}")
        print(f"Duplicate Rows: {quality_report['duplicate_rows']}")
        print(f"High Null Columns: {len(quality_report['high_null_columns'])}")
        print(f"Output File: {output_file}")
        print(f"Report File: {report_file}")
        print(f"{'=' * 80}\n")
        
        print(f"\n{'=' * 80}")
        print("Processing Completed Successfully!")
        print(f"End Time: {datetime.utcnow().isoformat()}")
        print(f"{'=' * 80}\n")
        
    except Exception as e:
        print(f"\n{'=' * 80}")
        print("ERROR: Processing Failed!")
        print(f"{'=' * 80}\n")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
