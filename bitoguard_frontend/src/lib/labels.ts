export const ALERT_STATUS_ZH: Record<string, string> = {
  open: "待處理",
  closed: "已關閉",
  reviewing: "審查中",
  monitoring: "監控中",
  escalated: "已升級",
  confirmed_suspicious: "已確認可疑",
  dismissed_false_positive: "已排除誤報",
}

export const CASE_STATUS_ZH: Record<string, string> = {
  open: "待處理",
  monitoring: "監控中",
  escalated: "已升級",
  closed_confirmed: "已確認結案",
  closed_dismissed: "已排除結案",
}

export const RISK_LEVEL_ZH: Record<string, string> = {
  low: "低風險",
  medium: "中風險",
  high: "高風險",
  critical: "極高風險",
}

export const RECOMMENDED_ACTION_ZH: Record<string, string> = {
  monitor: "持續監控",
  manual_review: "人工複核",
  hold_withdrawal: "暫停出金",
}

export const DECISION_ZH: Record<string, string> = {
  confirm_suspicious:      "確認可疑",
  dismiss_false_positive:  "排除誤報",
  escalate:                "升級案件",
  request_monitoring:      "加強監控",
}

export const DECISION_COLOR: Record<string, string> = {
  confirm_suspicious:     "bg-red-50 text-[#e53935] border-red-300 hover:bg-red-100",
  dismiss_false_positive: "bg-green-50 text-[#43a047] border-green-300 hover:bg-green-100",
  escalate:               "bg-orange-50 text-[#fb8c00] border-orange-300 hover:bg-orange-100",
  request_monitoring:     "bg-blue-50 text-[#1976d2] border-blue-300 hover:bg-blue-100",
}

export const TIMELINE_TYPE_ZH: Record<string, string> = {
  login:  "登入",
  trade:  "交易",
  crypto: "加密貨幣",
  fiat:   "法幣",
}

export const GRAPH_EVIDENCE_ZH: Record<string, string> = {
  shared_device_count:   "共用裝置數",
  shared_bank_count:     "共用銀行帳戶數",
  shared_wallet_count:   "共用錢包數",
  blacklist_1hop_count:  "1跳黑名單鄰居",
  blacklist_2hop_count:  "2跳黑名單鄰居",
  component_size:        "連通分量大小",
  fan_out_ratio:         "出金擴散比",
}

export const FEATURE_ZH: Record<string, string> = {
  // Fiat velocity
  fiat_in_to_crypto_out_2h:        "法幣入金後 2h 提領虛幣",
  fiat_in_to_crypto_out_6h:        "法幣入金後 6h 提領虛幣",
  fiat_in_to_crypto_out_24h:       "法幣入金後 24h 提領虛幣",
  // Profile / KYC
  monthly_income_twd:              "月收入 (TWD)",
  expected_monthly_volume_twd:     "預期月交易量",
  actual_volume_expected_ratio:    "實際交易量 / 預期交易量",
  actual_fiat_income_ratio:        "實際法幣入金 / 月收入",
  account_age_days:                "帳戶開戶天數",
  kyc_level_code:                  "KYC 等級",
  // Graph
  component_size:                  "關聯群體規模",
  shared_device_count:             "共用裝置關聯帳戶數",
  shared_bank_count:               "共用銀行帳戶關聯數",
  shared_wallet_count:             "共用錢包關聯數",
  blacklist_1hop_count:            "黑名單 1-hop 鄰居數",
  blacklist_2hop_count:            "黑名單 2-hop 鄰居數",
  fan_out_ratio:                   "出金擴散比",
  // IP / Device
  night_large_withdrawal_ratio:    "深夜大額提領比例",
  ip_country_switch_count:         "IP 國家切換次數",
  ip_n_entities:                   "IP 關聯帳戶數",
  ip_unique_ips:                   "使用 IP 數",
  // TWD fiat
  twd_dep_sum:                     "法幣入金總額 (TWD)",
  twd_wdr_sum:                     "法幣出金總額 (TWD)",
  twd_dep_7d_sum:                  "7 日法幣入金總額",
  twd_dep_30d_sum:                 "30 日法幣入金總額",
  twd_wdr_7d_sum:                  "7 日法幣出金總額",
  twd_wdr_30d_sum:                 "30 日法幣出金總額",
  twd_dep_burst_ratio:             "法幣入金爆發比",
  twd_dep_round_10k_ratio:         "整數萬元入金比",
  twd_dep_near_500k_ratio:         "接近 50 萬上限入金比",
  twd_dep_amt_entropy:             "法幣入金金額分佈熵值 (低=結構化)",
  twd_dep_span_days:               "法幣交易活躍天數",
  twd_all_count:                   "法幣交易總筆數",
  twd_weekend_share:               "法幣交易週末佔比",
  // Crypto
  crypto_wdr_twd_sum:              "虛幣出金總額 (TWD)",
  crypto_dep_twd_sum:              "虛幣入金總額 (TWD)",
  crypto_wdr_7d_sum:               "7 日虛幣出金總額",
  crypto_wdr_30d_sum:              "30 日虛幣出金總額",
  crypto_dep_7d_sum:               "7 日虛幣入金總額",
  crypto_wdr_burst_ratio:          "虛幣出金爆發比",
  crypto_wdr_to_dep_ratio:         "虛幣出金 / 入金比",
  crypto_n_currencies:             "使用虛幣種類數",
  crypto_n_protocols:              "使用鏈路協議數",
  crypto_trx_tx_share:             "TRX/TRC20 交易佔比",
  crypto_trx_amt_share:            "TRX/TRC20 金額佔比",
  crypto_n_from_wallets:           "接收錢包地址數",
  crypto_n_to_wallets:             "發送目標錢包數",
  crypto_from_wallet_conc:         "來源錢包集中度",
  crypto_weekend_share:            "虛幣交易週末佔比",
  crypto_wdr_amt_entropy:          "虛幣出金金額分佈熵值 (低=自動化分層洗錢)",
  // Cross-channel layering
  xch_cashout_ratio_lifetime:      "跨通道提現比 (全期)",
  xch_cashout_ratio_7d:            "跨通道提現比 (7 日)",
  xch_cashout_ratio_30d:           "跨通道提現比 (30 日)",
  xch_layering_intensity:          "分層洗錢強度指標",
  // Sequence
  fiat_dep_to_swap_buy_within_1h:        "1h 內法幣轉虛幣次數",
  fiat_dep_to_swap_buy_within_6h:        "6h 內法幣轉虛幣次數",
  fiat_dep_to_swap_buy_within_24h:       "24h 內法幣轉虛幣次數",
  fiat_dep_to_swap_buy_within_72h:       "72h 內法幣轉虛幣次數",
  crypto_dep_to_fiat_wdr_within_1h:      "1h 內虛幣入→法幣出次數",
  crypto_dep_to_fiat_wdr_within_6h:      "6h 內虛幣入→法幣出次數",
  crypto_dep_to_fiat_wdr_within_24h:     "24h 內虛幣入→法幣出次數",
  crypto_dep_to_fiat_wdr_within_72h:     "72h 內虛幣入→法幣出次數",
  fiat_dep_to_fiat_wdr_within_24h:       "24h 法幣入即出 (人頭帳戶信號)",
  fiat_dep_to_fiat_wdr_within_72h:       "72h 法幣入即出 (人頭帳戶信號)",
  dwell_hours:                           "首次入金到出金間隔 (小時)",
  early_3d_volume:                       "開戶前 3 天交易量",
  early_3d_count:                        "開戶前 3 天交易次數",
  // Rule signals
  rule_fast_cash_out_2h:           "規則: 快速提現 (2h)",
  rule_high_volume:                "規則: 高額交易",
  rule_structuring:                "規則: 疑似分拆交易",
  rule_new_device_withdrawal:      "規則: 新裝置出金",
  rule_fiat_passthrough:           "規則: 法幣入即出 (人頭帳戶)",
  rule_layering_burst:             "規則: 分層洗錢爆發",
  // Cross-channel interaction features
  trx_volume_signal:               "TRX 高量出金信號 (TRC20 佔比 × 出金額)",
  early_activity_ratio:            "早期帳戶活躍密度 (開戶 3 天量 / 帳戶年齡)",
  trx_cashout_signal:              "TRX 提現集中信號 (跨通道提現比 × TRX 佔比)",
  // Bipartite graph features
  rel_peer_count:                  "錢包共享同儕數",
  rel_has_peers:                   "有錢包共享同儕",
  graph_is_isolated:               "孤立帳戶 (無關聯)",
  ip_n_entities:                   "共享 IP 帳戶數",
  wallet_n_entities:               "關聯錢包數",
  wallet_mean_entity_deg:          "錢包平均連接度",
  wallet_max_entity_deg:           "錢包最大連接度",
}
