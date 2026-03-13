# Feature Dictionary

All features are computed at a daily snapshot granularity per user, stored in `features.feature_snapshots_user_day` (latest-day view) and `features.feature_snapshots_user_30d` (rolling 30-day view).

Feature version: `v1`

## Identity / Metadata Features

These are categorical identity fields from `canonical.users`. They are one-hot encoded for model input.

| Feature | Type | Description |
|---------|------|-------------|
| kyc_level | categorical | KYC verification level: email_verified, level1, level2 |
| occupation | categorical | Occupation code from user profile (career_{N}) |
| declared_source_of_funds | categorical | Declared fund source (income_source_{N}) |
| segment | categorical | Channel: web or app |
| monthly_income_twd | float | Self-declared monthly income in TWD (often null) |
| expected_monthly_volume_twd | float | Self-declared expected monthly trading volume in TWD (often null) |

## Fiat Transaction Features (TWD Transfers)

Lookback windows: 1-day, 7-day, 30-day relative to snapshot end.

| Feature | Type | Description |
|---------|------|-------------|
| fiat_in_1d | float | Sum of fiat deposit amounts (TWD) in last 1 day |
| fiat_out_1d | float | Sum of fiat withdrawal amounts (TWD) in last 1 day |
| fiat_in_7d | float | Sum of fiat deposit amounts (TWD) in last 7 days |
| fiat_out_7d | float | Sum of fiat withdrawal amounts (TWD) in last 7 days |
| fiat_in_30d | float | Sum of fiat deposit amounts (TWD) in last 30 days |
| fiat_out_30d | float | Sum of fiat withdrawal amounts (TWD) in last 30 days |

## Trade Order Features

| Feature | Type | Description |
|---------|------|-------------|
| trade_count_30d | int | Number of trade orders in last 30 days |
| trade_notional_30d | float | Total notional TWD value of trades in last 30 days |

## Crypto Transaction Features

| Feature | Type | Description |
|---------|------|-------------|
| crypto_withdraw_30d | float | Total TWD-equivalent value of crypto withdrawals in last 30 days |

## Velocity / Timing Features

These detect rapid conversion from fiat-in to crypto-out — a key money-laundering pattern.

| Feature | Type | Description |
|---------|------|-------------|
| fiat_in_to_crypto_out_2h | bool | True if any fiat deposit followed by crypto withdrawal within 2 hours |
| fiat_in_to_crypto_out_6h | bool | True if any fiat deposit followed by crypto withdrawal within 6 hours |
| fiat_in_to_crypto_out_24h | bool | True if any fiat deposit followed by crypto withdrawal within 24 hours |
| avg_dwell_time | float | Average hours between fiat deposit and earliest subsequent crypto withdrawal |
| min_dwell_time_hours | float | **Minimum** (fastest) fiat-deposit-to-crypto-withdrawal cycle time in hours — primary 快進快出之滯留時間 (quick in/out retention time) signal |
| quick_inout_count_24h | float | Number of fiat-deposit→crypto-withdrawal pairs completed within 24 hours |
| large_deposit_withdraw_gap | float | Hours between largest fiat deposit and its earliest crypto withdrawal |

## Login / Behavioral Features

Computed over login events in the 30-day lookback window.

| Feature | Type | Description |
|---------|------|-------------|
| geo_jump_count | int | Number of logins flagged as geographic jumps |
| vpn_ratio | float | Fraction of logins via VPN |
| new_device_ratio | float | Fraction of logins from previously-unseen devices |
| ip_country_switch_count | int | Number of distinct IP countries seen in 30-day window |
| night_login_ratio | float | Fraction of logins occurring between 00:00-05:59 |

## Nighttime / High-Risk Timing Features

| Feature | Type | Description |
|---------|------|-------------|
| night_large_withdrawal_ratio | float | Fraction of crypto withdrawals that are both nighttime (00:00-05:59) and >= 50,000 TWD |
| new_device_withdrawal_24h | bool | True if a crypto withdrawal occurred within 24h of a new-device login |

## Derived Ratio Features

| Feature | Type | Description |
|---------|------|-------------|
| actual_volume_expected_ratio | float | trade_notional_30d / expected_monthly_volume_twd (0 if denominator null or zero) |
| actual_fiat_income_ratio | float | (fiat_in_30d + fiat_out_30d) / monthly_income_twd (0 if denominator null or zero) |

## Graph Features

Graph features are computed from `canonical.entity_edges` using a point-in-time snapshot of the user-entity graph. Stored separately in `features.graph_features` and joined into the main snapshot tables.

| Feature | Type | Description |
|---------|------|-------------|
| shared_device_count | int | Number of other users sharing a device with this user |
| shared_bank_count | int | Number of other users sharing a bank account with this user |
| shared_wallet_count | int | Number of other users sharing a crypto wallet with this user |
| blacklist_1hop_count | int | Number of known-blacklist users reachable within 2 hops in the entity graph |
| blacklist_2hop_count | int | Number of known-blacklist users reachable at 3-4 hops in the entity graph |
| component_size | int | Total number of nodes in the connected component containing this user |
| fan_out_ratio | float | Distinct counterparty wallets / total crypto transfers (0 if no transfers) |

## NON_FEATURE_COLUMNS (Excluded from Model Input)

These columns are present in feature tables but are excluded from the model feature matrix:

| Column | Reason |
|--------|--------|
| feature_snapshot_id | Metadata identifier |
| user_id | Entity key |
| snapshot_date | Temporal key |
| feature_version | Pipeline version |
| hidden_suspicious_label | Target label — must not be a feature |
| scenario_types | Oracle metadata — must not be a feature |

## Feature Leakage Rules

1. `hidden_suspicious_label` must never appear in `feature_columns()` output
2. Temporal windows are always computed relative to `snapshot_end` (exclusive), preventing future leakage
3. Graph features use only edges with `snapshot_time < snapshot_end`
4. Training dataset filters positive labels to only include snapshots on or after `positive_effective_date` (the earliest observed blacklist date for that user), preventing pre-label leakage
