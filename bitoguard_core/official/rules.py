from __future__ import annotations

import json

import pandas as pd


RULE_DEFINITIONS = {
    "fast_cashout_24h": "台幣入金後 24 小時內提領虛幣",
    "shared_ip_ring": "共享 IP 關聯用戶達 3 人以上",
    "shared_wallet_ring": "共享錢包關聯用戶達 2 人以上",
    "high_relation_fanout": "內轉對手數高且 fan-out 明顯",
    "night_trade_burst": "深夜交易比例高且交易活躍",
    "market_order_burst": "市價交易比例高且短期成交集中",
}


def evaluate_official_rules(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[["user_id"]].copy()
    result["fast_cashout_24h"] = frame["fast_cashout_24h_flag"].astype(bool)
    result["shared_ip_ring"] = frame["shared_ip_user_count"] >= 3
    result["shared_wallet_ring"] = frame["shared_wallet_user_count"] >= 2
    result["high_relation_fanout"] = (frame["relation_unique_counterparty_count"] >= 3) & (frame["relation_fan_out_ratio"] >= 0.5)
    result["night_trade_burst"] = (frame["trade_night_ratio"] >= 0.5) & (frame["order_total_count"] >= 5)
    result["market_order_burst"] = (frame["trade_market_ratio"] >= 0.8) & (frame["trade_intraday_concentration"] >= 0.6)
    result["rule_score"] = result[list(RULE_DEFINITIONS)].sum(axis=1) / len(RULE_DEFINITIONS)
    result["top_reason_codes"] = result.apply(
        lambda row: json.dumps([name for name in RULE_DEFINITIONS if bool(row[name])], ensure_ascii=False),
        axis=1,
    )
    rule_flag_columns = list(RULE_DEFINITIONS)
    return result[["user_id", "rule_score", "top_reason_codes"] + rule_flag_columns]
