# Graph Schema

BitoGuard builds a heterogeneous entity graph over user-entity relationships, stored in `canonical.entity_edges` and consumed by the graph feature builder.

## Entity Types

| Entity Type | ID Format | Source |
|-------------|-----------|--------|
| user | user_id (string) | canonical.users |
| device | dev_{ip_hash} | Synthetic from source_ip_hash fields |
| wallet | wallet_hash string | crypto_transfer from/to wallet fields |
| ip | ip_hash string | login_events.ip_address |
| bank_account | bank_account_id | Empty (not in upstream source) |

## Edge Relation Types

All edges are stored in `canonical.entity_edges` with the schema:

```
edge_id         VARCHAR  PK (edge_{N:06d})
snapshot_time   TIMESTAMPTZ
src_type        VARCHAR
src_id          VARCHAR
relation_type   VARCHAR
dst_type        VARCHAR
dst_id          VARCHAR
```

### `uses_device`
- `src_type = user`, `dst_type = device`
- One edge per user-device link in `canonical.user_device_links`
- `snapshot_time = first_seen_at`
- Shared-device detection: two users sharing a device create a 2-hop path `user:A -> device:X -> user:B`

### `uses_bank_account`
- `src_type = user`, `dst_type = bank_account`
- One edge per user-bank link in `canonical.user_bank_links`
- Currently empty (bank accounts not in upstream source)

### `owns_wallet`
- `src_type = user`, `dst_type = wallet`
- One edge per crypto wallet with non-null user_id in `canonical.crypto_wallets`
- `snapshot_time = created_at`

### `crypto_transfer_to_wallet`
- `src_type = user`, `dst_type = wallet`
- One edge per crypto transaction with non-null `counterparty_wallet_id`
- `snapshot_time = occurred_at`
- Used to compute fan-out ratio: distinct counterparty wallets / total transfers

### `login_from_ip`
- `src_type = user`, `dst_type = ip`
- One edge per login event with non-null `ip_address`
- `snapshot_time = occurred_at`
- Enables IP-sharing detection across users

## Graph Feature Computation

Graph features are computed with a point-in-time filter: only edges with `snapshot_time < snapshot_end` are included.

### Shared-Entity Detection

For each user, shared entities are found by 2-hop traversal through intermediate entity nodes:

```
user:A --[uses_device]--> device:X --[uses_device]--> user:B
```

`shared_device_count` = |{user:B : user:B ≠ user:A reachable via device nodes}|

Same logic applies for `shared_bank_count` (via bank_account nodes) and `shared_wallet_count` (via wallet nodes).

### Blacklist Proximity

Using BFS from `user:{user_id}` with cutoff 4:

- `blacklist_1hop_count`: blacklisted users at graph distance 1-2
- `blacklist_2hop_count`: blacklisted users at graph distance 3-4

A user is considered blacklisted if their user_id appears in `canonical.blacklist_feed` with `observed_at < snapshot_end`.

### Component Size

`component_size` = size of the connected component containing `user:{user_id}` in the NetworkX undirected graph.

### Fan-Out Ratio

```
fan_out_ratio = distinct(counterparty_wallet_id) / total(crypto_transfer_to_wallet edges)
```

A high fan-out ratio (close to 1.0) means every transfer goes to a different wallet, which is indicative of smurfing or layering.

## Graph Size Limits

For the frontend visualization (`GET /users/{user_id}/graph`):
- Maximum nodes returned: 120
- Maximum edges returned: 240
- `is_truncated = True` if the graph was cut

## Notes

1. Devices are synthetic: `device_id = dev_{source_ip_hash}`. There is no authoritative device fingerprint from the upstream source.
2. IP addresses from `login_events.ip_address` are ip_hash values — treated as opaque identifiers for clustering, not resolved geographically.
3. Bank accounts are empty in the current ingestion path; `shared_bank_count` will always be 0 until upstream bank data becomes available.
4. The graph is undirected for connectivity computation purposes (NetworkX `nx.Graph`), even though edges are directional at the schema level.
