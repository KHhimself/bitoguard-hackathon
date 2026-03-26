# BitoGuard Product Overview

BitoGuard is a production-grade Anti-Money Laundering (AML) and fraud-risk detection system for cryptocurrency exchanges, specifically built for the BitoPro platform.

## Core Purpose

Detect, explain, and monitor suspicious activity on cryptocurrency exchanges using a 6-module architecture combining rule-based, statistical, supervised ML, anomaly detection, graph analysis, and operational monitoring.

## Key Capabilities

- Real-time risk scoring for users based on transaction patterns
- Alert generation with SHAP-based explanations
- Graph analysis for detecting shared IP/wallet/blacklist proximity
- Incremental data refresh with watermark checkpointing
- Feature drift detection for model health monitoring
- User 360-degree view with transaction history and risk factors

## Architecture Modules

1. **M1: Rules** - 11 deterministic AML rules with severity-weighted scoring
2. **M2: Statistical** - Peer-deviation features, cohort percentile ranks, rolling windows
3. **M3: Supervised** - LightGBM with temporal splits, precision@K optimization
4. **M4: Anomaly** - IsolationForest for novelty detection
5. **M5: Graph** - NetworkX heterogeneous graph analysis (IP/wallet/user relationships)
6. **M6: Ops** - SHAP case reports, drift detection, incremental refresh

## Target Users

- Compliance officers reviewing alerts
- Risk analysts investigating suspicious patterns
- Operations teams monitoring model health
- Developers maintaining the AML pipeline
