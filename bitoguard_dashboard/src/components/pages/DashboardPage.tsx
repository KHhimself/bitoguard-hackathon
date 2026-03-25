"use client";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { AlertTriangle, Shield, CheckCircle, Eye, ChevronRight, BarChart3, Bell } from "lucide-react";
import { api } from "@/lib/api";
import { StatCard } from "@/components/ui/StatCard";
import { SectionTitle } from "@/components/ui/SectionTitle";
import { C, HEX } from "@/components/ui/constants";

export function DashboardPage({ setActive, setQueryId }: { setActive: (p: string) => void; setQueryId: (id: string) => void }) {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.getStats });
  const { data: alerts } = useQuery({ queryKey: ["dashAlerts"], queryFn: () => api.getAlerts({ page_size: 20 }) });
  const { data: metrics } = useQuery({ queryKey: ["dashMetrics"], queryFn: api.getModelMetrics });

  const critical = stats?.risk_level_counts.critical ?? 0;
  const high = stats?.risk_level_counts.high ?? 0;
  const medium = stats?.risk_level_counts.medium ?? 0;
  const flagged = critical + high;

  // Show full histogram
  const histogramData = stats?.risk_score_histogram ?? [];

  const handleAlertClick = (userId: string) => {
    setQueryId(userId);
    setActive("query");
  };

  const riskDot = (score: number) =>
    score >= 80 ? "bg-red-500 animate-pulse" : score >= 60 ? "bg-orange-400" : score >= 35 ? "bg-amber-400" : "bg-emerald-400";
  const riskText = (score: number) =>
    score >= 80 ? "text-red-500" : score >= 60 ? "text-orange-500" : score >= 35 ? "text-amber-500" : "text-emerald-500";

  const cm = metrics?.confusion_matrix;

  return (
    <div className="space-y-5">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={AlertTriangle} label="風險用戶" value={flagged + medium} />
        <StatCard icon={Shield} label="Critical" value={critical} />
        <StatCard icon={Shield} label="High" value={high} />
        <StatCard icon={CheckCircle} label="Precision" value={stats?.model_metrics_summary.precision.toFixed(4) ?? "—"} />
      </div>

      {/* Main Content: Alert List (2/3) + Right Panel (1/3) */}
      <div className="grid grid-cols-3 gap-4">
        {/* Alert List - takes 2/3 */}
        <div className="col-span-2 bg-white rounded-2xl border border-slate-100 flex flex-col">
          <div className="px-6 pt-5 pb-3 border-b border-slate-50">
            <div className="flex items-center justify-between">
              <SectionTitle icon={Bell} title="警報列表" subtitle="依風險分數排序，點擊可查看詳情" />
              <button onClick={() => setActive("graph")}
                className="text-xs text-blue-500 hover:text-blue-700 transition flex items-center gap-1">
                查看圖譜 <ChevronRight size={12} />
              </button>
            </div>
          </div>

          {/* Table Header */}
          <div className="grid grid-cols-[1fr_80px_120px_80px] px-6 py-2 text-xs font-medium text-text-muted border-b border-slate-50">
            <span>用戶 ID</span>
            <span className="text-center">分數</span>
            <span className="text-center">風險等級</span>
            <span />
          </div>

          {/* Table Body */}
          <div className="flex-1 overflow-y-auto max-h-[420px]">
            {(alerts?.items ?? []).map((a) => {
              const score = Math.round(a.risk_score ?? 0);
              const levelColor = a.risk_level === "critical" ? HEX.danger : a.risk_level === "high" ? HEX.warning : "#FFE066";
              return (
                <button
                  key={a.alert_id}
                  onClick={() => handleAlertClick(a.user_id)}
                  className="w-full grid grid-cols-[1fr_80px_120px_80px] items-center px-6 py-3 hover:bg-slate-50 transition text-left border-b border-slate-50 last:border-0 group"
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${riskDot(score)}`} />
                    <div>
                      <div className="text-sm font-semibold text-slate-700">{a.user_id}</div>
                      <div className="text-xs text-text-muted">{new Date(a.created_at).toLocaleDateString("zh-TW")}</div>
                    </div>
                  </div>
                  <div className="text-center">
                    <span className={`text-sm font-bold ${riskText(score)}`}>{score}</span>
                  </div>
                  <div className="text-center">
                    <span className="text-xs font-medium px-2 py-1 rounded-full"
                      style={{ background: `${levelColor}18`, color: levelColor }}>
                      {a.risk_level}
                    </span>
                  </div>
                  <div className="text-right">
                    <ChevronRight size={14} className="text-slate-300 group-hover:text-slate-500 transition inline" />
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right Panel */}
        <div className="space-y-4">
          {/* Risk Distribution (filtered >10) */}
          <div className="bg-white rounded-2xl p-5 border border-slate-100">
            <SectionTitle icon={BarChart3} title="風險分數分布" subtitle="全體用戶（0-100 分）" />
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={histogramData} barCategoryGap="10%">
                <XAxis dataKey="range" tick={{ fontSize: 9, fill: "#64748B", angle: -45, textAnchor: "end" }} axisLine={false} tickLine={false} interval={0} height={45} />
                <YAxis tick={{ fontSize: 9, fill: "#64748B" }} axisLine={false} tickLine={false} scale="log" domain={[1, "auto"]} allowDataOverflow />
                <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }}
                  formatter={(v: number) => [v.toLocaleString(), "用戶數"]} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {histogramData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Model Performance Summary */}
          <div className="bg-white rounded-2xl p-5 border border-slate-100">
            <SectionTitle icon={Eye} title="模型表現" subtitle="交叉驗證結果" />
            <div className="space-y-3 mt-2">
              {[
                { label: "F1 Score", value: metrics?.f1, color: HEX.primary },
                { label: "Precision", value: metrics?.precision, color: HEX.accent },
                { label: "Recall", value: metrics?.recall, color: HEX.warning },
                { label: "PR-AUC", value: metrics?.average_precision, color: HEX.violet },
              ].map(({ label, value, color }) => (
                <div key={label}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-500">{label}</span>
                    <span className="font-semibold text-slate-700">{value?.toFixed(4) ?? "—"}</span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-100 rounded-full">
                    <div className="h-full rounded-full transition-all duration-1000"
                      style={{ width: `${(value ?? 0) * 100}%`, background: color }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Mini Confusion Matrix */}
            {cm && (
              <div className="mt-4 pt-3 border-t border-slate-100">
                <div className="text-xs text-text-muted mb-2">混淆矩陣</div>
                <div className="grid grid-cols-2 gap-1.5 text-center">
                  <div className="rounded-lg py-2" style={{ background: "#DCFCE7" }}>
                    <div className="text-sm font-bold" style={{ color: HEX.safe }}>{cm.tp.toLocaleString()}</div>
                    <div className="text-xs text-text-muted">TP</div>
                  </div>
                  <div className="rounded-lg py-2" style={{ background: "#FEE2E2" }}>
                    <div className="text-sm font-bold" style={{ color: HEX.danger }}>{cm.fn.toLocaleString()}</div>
                    <div className="text-xs text-text-muted">FN</div>
                  </div>
                  <div className="rounded-lg py-2" style={{ background: "#FEF3C7" }}>
                    <div className="text-sm font-bold" style={{ color: HEX.warning }}>{cm.fp.toLocaleString()}</div>
                    <div className="text-xs text-text-muted">FP</div>
                  </div>
                  <div className="rounded-lg py-2" style={{ background: "#DBEAFE" }}>
                    <div className="text-sm font-bold" style={{ color: HEX.primary }}>{cm.tn.toLocaleString()}</div>
                    <div className="text-xs text-text-muted">TN</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
