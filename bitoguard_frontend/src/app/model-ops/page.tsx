"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

interface DriftFeature {
  feature: string
  zero_rate_delta: number
  mean_rel_change: number
  std_rel_change: number
}

interface DriftResult {
  snapshot_from: string
  snapshot_to: string
  drifted_features: DriftFeature[]
  total_checked: number
  total_drifted: number
  health_ok: boolean
}

interface ThresholdRow {
  threshold: number
  precision: number
  recall: number
  f1: number
}

interface ScenarioRow {
  scenario: string
  count: number
  precision: number
  recall: number
}

interface CalibrationBin {
  mean_predicted: number
  fraction_positive: number
}

interface FeatureImportanceRow {
  feature: string
  importance_gain: number
  importance_pct: number
}

interface ModelMetrics {
  model_version: string
  holdout_rows: number
  holdout_positives: number
  holdout_negatives: number
  precision: number
  recall: number
  f1: number
  fpr: number
  average_precision: number
  confusion_matrix: { tn: number; fp: number; fn: number; tp: number }
  precision_at_k: Record<string, number>
  recall_at_k: Record<string, number>
  calibration: { brier_score: number; n_bins: number; bins: CalibrationBin[] }
  feature_importance_top20: FeatureImportanceRow[]
  threshold_sensitivity: ThresholdRow[]
  scenario_breakdown: ScenarioRow[]
}

export default function ModelOpsPage() {
  const { data: metrics, isLoading, error } = useQuery({
    queryKey: ["modelMetrics"],
    queryFn: () => api.getModelMetrics() as Promise<ModelMetrics>,
    staleTime: 300_000,
  })
  const { data: drift } = useQuery({
    queryKey: ["driftMetrics"],
    queryFn: () => api.getDriftMetrics() as Promise<DriftResult>,
    refetchInterval: 300_000,
    refetchIntervalInBackground: false,
  })

  return (
    <div className="max-w-[960px] mx-auto space-y-4">
      <div>
        <h1 className="text-[22px] font-semibold text-[#1a1d2e]">模型指標</h1>
        <p className="text-[13px] text-[#9ca3af] mt-0.5">檢視風險模型的驗證結果與閾值敏感度分析</p>
      </div>

      {isLoading && <div className="text-[#9ca3af] text-center py-8">載入中...</div>}
      {error && <div className="text-[#e53935] text-center py-8">無法載入模型指標，請確認後端服務是否正常運行</div>}

      {metrics && (
        <div className="space-y-4">
          {/* 版本與核心指標 */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "模型版本", value: metrics.model_version },
              { label: "Precision", value: metrics.precision.toFixed(4) },
              { label: "Recall", value: metrics.recall.toFixed(4) },
              { label: "F1 Score", value: metrics.f1.toFixed(4) },
              { label: "FPR (偽陽率)", value: metrics.fpr.toFixed(4) },
              { label: "Average Precision", value: metrics.average_precision.toFixed(4) },
              { label: "Holdout 樣本", value: (metrics.holdout_rows ?? 0).toLocaleString() },
              { label: "Holdout 正樣本", value: (metrics.holdout_positives ?? 0).toLocaleString() },
              { label: "Holdout 負樣本", value: (metrics.holdout_negatives ?? 0).toLocaleString() },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white rounded-xl border border-[#e5e7eb] px-4 py-3 shadow-sm">
                <p className="text-[11px] text-[#9ca3af] font-semibold uppercase tracking-wider">{label}</p>
                <p className="text-[18px] font-semibold text-[#1a1d2e] mt-0.5">{value}</p>
              </div>
            ))}
          </div>

          {/* 混淆矩陣 */}
          <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-[#e5e7eb]">
              <h2 className="text-[14px] font-semibold text-[#1a1d2e]">混淆矩陣</h2>
            </div>
            <div className="p-4 grid grid-cols-4 gap-3">
              {[
                { label: "True Negative (TN)", value: metrics.confusion_matrix.tn, color: "#43a047" },
                { label: "False Positive (FP)", value: metrics.confusion_matrix.fp, color: "#fb8c00" },
                { label: "False Negative (FN)", value: metrics.confusion_matrix.fn, color: "#fb8c00" },
                { label: "True Positive (TP)", value: metrics.confusion_matrix.tp, color: "#5c6bc0" },
              ].map(({ label, value, color }) => (
                <div key={label} className="rounded-lg border border-[#e5e7eb] px-4 py-3 text-center">
                  <p className="text-[11px] text-[#9ca3af] font-semibold">{label}</p>
                  <p className="text-[24px] font-semibold mt-0.5" style={{ color }}>{value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Precision@K / Recall@K */}
          {metrics.precision_at_k && Object.keys(metrics.precision_at_k).length > 0 && (
            <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-[#e5e7eb]">
                <h2 className="text-[14px] font-semibold text-[#1a1d2e]">Precision@K / Recall@K</h2>
                <p className="text-[11px] text-[#9ca3af] mt-0.5">AML稽核容量固定時，前K名使用者的精準度與召回率</p>
              </div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-[#f9fafb] border-b border-[#e5e7eb]">
                    {["K", "Precision@K", "Recall@K"].map((h) => (
                      <th key={h} className="px-4 py-2 text-left text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(metrics.precision_at_k).map((k) => (
                    <tr key={k} className="border-b border-[#f3f4f6] hover:bg-[#f9fafb]">
                      <td className="px-4 py-2 font-mono font-semibold text-[#5c6bc0]">{k.replace("P@", "")}</td>
                      <td className="px-4 py-2 font-mono">{(metrics.precision_at_k[k] ?? 0).toFixed(4)}</td>
                      <td className="px-4 py-2 font-mono">{(metrics.recall_at_k?.[k.replace("P@", "R@")] ?? 0).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 校準摘要 + 特徵重要度 */}
          <div className="grid grid-cols-2 gap-3">
            {metrics.calibration?.brier_score !== undefined && (
              <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm p-4">
                <h2 className="text-[14px] font-semibold text-[#1a1d2e] mb-3">模型校準</h2>
                <div className="flex items-center gap-4 mb-3">
                  <div>
                    <p className="text-[11px] text-[#9ca3af] uppercase tracking-wider">Brier Score</p>
                    <p className="text-[24px] font-semibold text-[#43a047]">{metrics.calibration.brier_score.toFixed(4)}</p>
                  </div>
                  <div className="text-[12px] text-[#6b7280]">
                    <p>0 = 完美校準</p>
                    <p>1 = 最差校準</p>
                  </div>
                </div>
              </div>
            )}

            {metrics.feature_importance_top20?.length > 0 && (
              <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-[#e5e7eb]">
                  <h2 className="text-[14px] font-semibold text-[#1a1d2e]">特徵重要度 Top 5</h2>
                  <p className="text-[11px] text-[#9ca3af] mt-0.5">LightGBM gain-based importance</p>
                </div>
                <div className="p-3 space-y-2">
                  {metrics.feature_importance_top20.slice(0, 5).map((row) => (
                    <div key={row.feature} className="flex items-center gap-2">
                      <div className="w-32 text-[11px] text-[#6b7280] truncate" title={row.feature}>{row.feature}</div>
                      <div className="flex-1 bg-[#f3f4f6] rounded-full h-2">
                        <div
                          className="bg-[#5c6bc0] h-2 rounded-full"
                          style={{ width: `${Math.min(100, row.importance_pct)}%` }}
                        />
                      </div>
                      <div className="w-12 text-[11px] font-mono text-right text-[#1a1d2e]">{row.importance_pct.toFixed(1)}%</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 閾值敏感度 */}
          {metrics.threshold_sensitivity.length > 0 && (
            <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-[#e5e7eb]">
                <h2 className="text-[14px] font-semibold text-[#1a1d2e]">閾值敏感度分析</h2>
              </div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-[#f9fafb] border-b border-[#e5e7eb]">
                    {["閾值", "Precision", "Recall", "F1"].map((h) => (
                      <th key={h} className="px-4 py-2 text-left text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metrics.threshold_sensitivity.map((row) => (
                    <tr key={row.threshold} className="border-b border-[#f3f4f6] hover:bg-[#f9fafb]">
                      <td className="px-4 py-2 font-mono font-semibold text-[#5c6bc0]">{row.threshold.toFixed(2)}</td>
                      <td className="px-4 py-2 font-mono">{row.precision.toFixed(4)}</td>
                      <td className="px-4 py-2 font-mono">{row.recall.toFixed(4)}</td>
                      <td className="px-4 py-2 font-mono">{row.f1.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 情境分析 */}
          {metrics.scenario_breakdown.length > 0 && (
            <div className="bg-white rounded-xl border border-[#e5e7eb] shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-[#e5e7eb]">
                <h2 className="text-[14px] font-semibold text-[#1a1d2e]">情境別表現</h2>
              </div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-[#f9fafb] border-b border-[#e5e7eb]">
                    {["情境", "樣本數", "Precision", "Recall"].map((h) => (
                      <th key={h} className="px-4 py-2 text-left text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metrics.scenario_breakdown.map((row) => (
                    <tr key={row.scenario} className="border-b border-[#f3f4f6] hover:bg-[#f9fafb]">
                      <td className="px-4 py-2 font-semibold">{row.scenario}</td>
                      <td className="px-4 py-2 font-mono">{row.count}</td>
                      <td className="px-4 py-2 font-mono">{row.precision.toFixed(4)}</td>
                      <td className="px-4 py-2 font-mono">{row.recall.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 特徵漂移健康狀態 */}
      {drift && (
        <div className={`rounded-xl border shadow-sm overflow-hidden ${drift.health_ok ? "border-[#e5e7eb] bg-white" : "border-[#ef9a9a] bg-[#fff5f5]"}`}>
          <div className="px-4 py-3 border-b border-[#e5e7eb] flex items-center justify-between">
            <div>
              <h2 className="text-[14px] font-semibold text-[#1a1d2e]">特徵漂移健康狀態</h2>
              <p className="text-[11px] text-[#9ca3af] mt-0.5">{drift.snapshot_from} → {drift.snapshot_to}</p>
            </div>
            <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${drift.health_ok ? "bg-[#e8f5e9] text-[#2e7d32]" : "bg-[#ffebee] text-[#c62828]"}`}>
              {drift.health_ok ? "HEALTHY" : `${drift.total_drifted} DRIFTED`}
            </span>
          </div>
          <div className="p-4 flex gap-6 text-[13px]">
            <div>
              <p className="text-[11px] text-[#9ca3af] uppercase tracking-wider">檢查特徵數</p>
              <p className="text-[20px] font-semibold text-[#1a1d2e]">{drift.total_checked}</p>
            </div>
            <div>
              <p className="text-[11px] text-[#9ca3af] uppercase tracking-wider">漂移特徵數</p>
              <p className={`text-[20px] font-semibold ${drift.total_drifted > 0 ? "text-[#e53935]" : "text-[#43a047]"}`}>{drift.total_drifted}</p>
            </div>
          </div>
          {drift.drifted_features.length > 0 && (
            <table className="w-full text-[13px] border-t border-[#e5e7eb]">
              <thead>
                <tr className="bg-[#f9fafb]">
                  {["特徵", "零值率變化", "均值相對變化", "標準差相對變化"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left text-[11px] font-semibold text-[#9ca3af] uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {drift.drifted_features.map((row) => (
                  <tr key={row.feature} className="border-t border-[#f3f4f6]">
                    <td className="px-4 py-2 font-mono text-[#e53935]">{row.feature}</td>
                    <td className="px-4 py-2 font-mono">{(row.zero_rate_delta * 100).toFixed(1)}pp</td>
                    <td className="px-4 py-2 font-mono">{(row.mean_rel_change * 100).toFixed(1)}%</td>
                    <td className="px-4 py-2 font-mono">{(row.std_rel_change * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
