# Data Contract

## Overview

BitoGuard ingests data from the BitoPro AWS Event API (PostgREST at `https://aws-event-api.bitopro.com`) and projects it into a well-defined internal canonical schema stored in DuckDB.

## Upstream Source Tables

### `user_info`
- Primary key: `user_id` (integer, coerced to VARCHAR internally)
- Time fields: `confirmed_at`, `level1_finished_at`, `level2_finished_at` (ISO-8601 strings, treated as Asia/Taipei if no tzinfo)
- Derived internal fields:
  - `kyc_level`: `level2` if `level2_finished_at` non-null, else `level1` if `level1_finished_at` non-null, else `email_verified`
  - `created_at`: `MIN(level1_finished_at, confirmed_at, level2_finished_at)`
  - `segment`: mapped from `user_source` (0=web, 1=app)
  - `occupation`: `career_{career}` when `career` is non-null
  - `declared_source_of_funds`: `income_source_{income_source}` when non-null

### `twd_transfer`
- Primary key: `id`
- Time field: `created_at` (Asia/Taipei if naive)
- Scaled fields: `ori_samount` → amount_twd = value / 1e8
- Derived: `direction` = deposit if `kind=0` else withdrawal
- IP-like device proxy: `source_ip_hash` → used to derive synthetic login/device records

### `usdt_twd_trading`
- Primary key: `id`
- Time field: `updated_at`
- Scaled fields: `trade_samount` → quantity = value / 1e8; `twd_srate` → price_twd = value / 1e8
- Derived: `side` = buy if `is_buy=1` else sell
- Derived: `order_type` = market if `is_market=1` else limit

### `usdt_swap`
- Primary key: `id`
- Time field: `created_at`
- Scaled fields: `currency_samount` → quantity = value / 1e8; `twd_samount` → notional_twd = value / 1e8

### `crypto_transfer`
- Primary key: `id`
- Time field: `created_at`
- Scaled fields: `ori_samount` → amount_asset = value / 1e8; `twd_srate` → rate_twd = value / 1e8
- Derived: `direction` = deposit if `kind=0` else withdrawal
- Derived: `network` = protocol mapping (0=SELF, 1=ERC20, 2=OMNI, 3=BNB, 4=TRC20, 5=BSC, 6=POLYGON)
- Derived wallets: `from_wallet_hash` / `to_wallet_hash` → `wallet_id` / `counterparty_wallet_id` per direction
- IP-like device proxy: `source_ip_hash`

### `train_label`
- Primary key: `user_id`
- `status=1` → positive suspicious label; used as ground-truth target
- NOT used as a feature; used exclusively for `ops.oracle_user_labels` and `canonical.blacklist_feed`

## Internal Canonical Schema

All canonical tables live in the `canonical` DuckDB schema. Timestamps are stored as TIMESTAMPTZ (UTC).

### `canonical.users`
| Column | Type | Notes |
|--------|------|-------|
| user_id | VARCHAR | PK |
| created_at | TIMESTAMPTZ | Derived min of KYC timestamps |
| segment | VARCHAR | web or app |
| kyc_level | VARCHAR | email_verified, level1, level2 |
| occupation | VARCHAR | career_{N} or null |
| monthly_income_twd | DOUBLE | null (not in upstream) |
| expected_monthly_volume_twd | DOUBLE | null (not in upstream) |
| declared_source_of_funds | VARCHAR | income_source_{N} or null |
| residence_country | VARCHAR | null (not in upstream) |
| residence_city | VARCHAR | null (not in upstream) |
| nationality | VARCHAR | null (not in upstream) |
| activity_window | VARCHAR | "{earliest}..{latest}" date range |

### `canonical.fiat_transactions`
| Column | Type | Notes |
|--------|------|-------|
| fiat_txn_id | VARCHAR | PK: twd_{id} or book_{id} |
| user_id | VARCHAR | FK → users |
| occurred_at | TIMESTAMPTZ | |
| direction | VARCHAR | deposit or withdrawal |
| amount_twd | DOUBLE | Scaled from ori_samount / 1e8 |
| currency | VARCHAR | TWD |
| bank_account_id | VARCHAR | null (not in upstream) |
| method | VARCHAR | bank_transfer or instant_swap |
| status | VARCHAR | completed |

### `canonical.trade_orders`
| Column | Type | Notes |
|--------|------|-------|
| trade_id | VARCHAR | PK: book_{id} or swap_{id} |
| user_id | VARCHAR | FK → users |
| occurred_at | TIMESTAMPTZ | |
| side | VARCHAR | buy or sell |
| base_asset | VARCHAR | USDT |
| quote_asset | VARCHAR | TWD |
| price_twd | DOUBLE | Scaled / 1e8 |
| quantity | DOUBLE | Scaled / 1e8 |
| notional_twd | DOUBLE | quantity * price_twd |
| fee_twd | DOUBLE | 0.0 |
| order_type | VARCHAR | market, limit, or instant_swap |
| status | VARCHAR | filled |

### `canonical.crypto_transactions`
| Column | Type | Notes |
|--------|------|-------|
| crypto_txn_id | VARCHAR | PK: crypto_{id} |
| user_id | VARCHAR | FK → users |
| occurred_at | TIMESTAMPTZ | |
| direction | VARCHAR | deposit or withdrawal |
| asset | VARCHAR | Uppercase currency code |
| network | VARCHAR | Protocol label |
| wallet_id | VARCHAR | User-side wallet hash |
| counterparty_wallet_id | VARCHAR | External wallet hash |
| amount_asset | DOUBLE | Scaled / 1e8 |
| amount_twd_equiv | DOUBLE | amount_asset * rate_twd |
| tx_hash | VARCHAR | null (not in upstream) |
| status | VARCHAR | completed |

### `canonical.login_events`
Synthetic table derived from `source_ip_hash` fields across fiat/trade/crypto tables.

| Column | Type | Notes |
|--------|------|-------|
| login_id | VARCHAR | PK: login_{event_id} |
| user_id | VARCHAR | FK → users |
| occurred_at | TIMESTAMPTZ | From parent event time |
| device_id | VARCHAR | dev_{ip_hash} |
| ip_address | VARCHAR | ip_hash value |
| ip_country | VARCHAR | null (not derivable) |
| ip_city | VARCHAR | null (not derivable) |
| is_vpn | BOOLEAN | False (not derivable) |
| is_new_device | BOOLEAN | True if first occurrence per user |
| is_geo_jump | BOOLEAN | False (not derivable) |
| success | BOOLEAN | True |

### `canonical.devices`
Synthetic table derived from unique `source_ip_hash` values seen.

### `canonical.user_device_links`
Synthetic table linking users to their device_ids, with primary device marked by highest visit count.

### `canonical.crypto_wallets`
Derived from `from_wallet_hash` / `to_wallet_hash` in crypto_transfer events.

### `canonical.blacklist_feed`
Populated from `train_label` rows where `status=1`.

| Column | Type | Notes |
|--------|------|-------|
| blacklist_entry_id | VARCHAR | PK: kbl_{user_id} |
| user_id | VARCHAR | |
| observed_at | TIMESTAMPTZ | Earliest activity time for user |
| source | VARCHAR | bitopro_train_label |
| reason_code | VARCHAR | train_label_status_1 |
| is_active | BOOLEAN | True |

### `canonical.entity_edges`
Graph edges rebuilt after each sync.

| Column | Type | Notes |
|--------|------|-------|
| edge_id | VARCHAR | PK: edge_{N:06d} |
| snapshot_time | TIMESTAMPTZ | Time edge was observed |
| src_type | VARCHAR | user |
| src_id | VARCHAR | user_id |
| relation_type | VARCHAR | uses_device, owns_wallet, crypto_transfer_to_wallet, login_from_ip |
| dst_type | VARCHAR | device, wallet, ip, bank_account |
| dst_id | VARCHAR | Entity identifier |

## Data Quality Rules

1. `null_primary_key`: rows with null PKs are dropped and recorded in `ops.data_quality_issues`
2. `duplicate_primary_key`: duplicates deduplicated by `_loaded_at` desc (latest wins)
3. Amount scaling: all `ori_samount`, `twd_srate`, `trade_samount`, `twd_srate`, `currency_samount`, `twd_samount` fields divide by 1e8
4. Timezone normalization: naive datetimes from upstream are treated as Asia/Taipei (UTC+8)
5. `source_ip_hash = null` is NOT treated as suspicious; it simply means no synthetic login event is generated
6. Label column (`train_label.status`) must never appear in feature tables

## Forbidden Feature Columns

The following fields are stripped before model training and must never appear in `features.*` tables as predictors:
- `hidden_suspicious_label`
- `observed_blacklist_label`
- `scenario_types`
- `evidence_tags`
- Any column named `status` from user_info
