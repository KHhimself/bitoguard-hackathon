# Rule Engine Rulebook

The BitoGuard rule engine (`bitoguard_core/models/rule_engine.py`) evaluates a set of deterministic AML monitoring rules against feature snapshots. Rules produce analyst-readable boolean flags and a normalized rule score.

## Rule Definitions

### `fast_cash_out_2h`
**Description**: 法幣入金後 2 小時內提領虛幣 (Fiat deposit followed by crypto withdrawal within 2 hours)

**Feature**: `fiat_in_to_crypto_out_2h == True`

**AML Pattern**: Rapid conversion of fiat to crypto is a classic money-laundering technique — "cash-out" layering. The 2-hour threshold targets near-instant conversion with minimal dwell time.

**Risk weight**: High. This is the strongest single-rule indicator of layering.

---

### `new_device_new_ip_large_withdraw`
**Description**: 新裝置、新 IP 且出現大額提領 (New device + new IP + large withdrawal)

**Condition**: `new_device_withdrawal_24h == True AND ip_country_switch_count >= 2 AND crypto_withdraw_30d >= 50000`

**AML Pattern**: Account takeover or muling — a new unrecognized device appears, IP country changes (suggesting a different actor), and a large crypto withdrawal follows. The 50,000 TWD threshold (~USD 1,500) targets above-threshold suspicious activity.

**Risk weight**: High. Combines device anomaly, geo anomaly, and volume threshold.

---

### `night_new_device_withdraw`
**Description**: 深夜提領且伴隨新裝置跡象 (Nighttime withdrawal with new device signals)

**Condition**: `night_large_withdrawal_ratio > 0 AND new_device_ratio > 0`

**AML Pattern**: Unauthorized access often occurs outside business hours. A user who has a non-zero ratio of night-time large withdrawals AND has ever logged in from a new device is flagged for review.

**Risk weight**: Medium. Often accompanies account-takeover scenarios.

---

### `shared_device_ring`
**Description**: 共用裝置關聯帳戶達 3 人以上 (Shared-device ring: 3+ linked accounts)

**Condition**: `shared_device_count >= 3`

**AML Pattern**: Multiple accounts sharing a device strongly suggests a coordinated ring — either an orchestrated fraud operation or a mule network controlled by a single actor. The threshold of 3 balances sensitivity against false positives (e.g., family members using a shared computer).

**Risk weight**: Medium-High. Graph-based signal; requires graph rebuild.

---

### `blacklist_2hop`
**Description**: 與黑名單帳戶存在 2-hop 內關聯 (Within 2 hops of a known blacklist user)

**Condition**: `blacklist_2hop_count >= 1`

**AML Pattern**: Guilt-by-association: a user closely connected in the entity graph to a known-bad actor should receive heightened scrutiny. 2-hop means connected through at most one intermediate entity (e.g., sharing a device with a blacklisted user's device).

**Risk weight**: Medium. Should not be the sole basis for action without additional signals.

---

## Rule Score Computation

```python
rule_score = sum(rule_hit_flags) / len(RULE_DEFINITIONS)
```

The score is in [0, 1]. All rules are weighted equally at 1/5 = 0.2 per hit.

## Risk Score Composition

The final composite risk score (0-100) combines all four detection layers:

```
risk_score = (
    0.35 * rule_score          # Rule/monitoring layer
  + 0.45 * model_probability   # LightGBM supervised model
  + 0.10 * anomaly_score       # IsolationForest novelty
  + 0.10 * graph_risk          # Graph proximity score
) * 100
```

## Risk Level Thresholds

| Risk Level | Score Range |
|------------|-------------|
| low | 0 – 35 |
| medium | 35 – 60 |
| high | 60 – 80 |
| critical | 80 – 100 |

Only `high` and `critical` risk levels generate alerts.

## Alert Disposition Decisions

| Decision | Case Status | Alert Status |
|----------|-------------|--------------|
| confirm_suspicious | closed_confirmed | confirmed_suspicious |
| dismiss_false_positive | closed_dismissed | dismissed_false_positive |
| escalate | escalated | escalated |
| request_monitoring | monitoring | monitoring |

## Adding New Rules

1. Add the rule key and Chinese/English description to `RULE_DEFINITIONS` in `rule_engine.py`
2. Add the boolean evaluation logic to `evaluate_rules()`
3. Update `docs/RULEBOOK.md` (this file) with full AML pattern description
4. Add a test case in `tests/test_model_pipeline.py` or a new `tests/test_rules.py`
5. Consider whether the new rule requires a new feature — if so, update `features/build_features.py` and `docs/FEATURE_DICTIONARY.md`

## Governance Notes

- Rules are analyst-readable and explain-first: every alert must show which rules were hit
- Rules should not use label-derived features (no `hidden_suspicious_label`, no direct `blacklist_feed` join inside rule logic)
- Rule thresholds are domain-expert parameters; changes should be logged in the risk register
- `source_ip_hash = null` does NOT trigger any rule — null IP is not inherently suspicious
