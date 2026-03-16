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
