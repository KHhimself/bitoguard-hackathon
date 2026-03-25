"use client";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { Zap, CheckCircle, Eye, TrendingUp, BarChart3, Grid3X3 } from "lucide-react";
import { api } from "@/lib/api";
import { SectionTitle } from "@/components/ui/SectionTitle";
import { C, HEX } from "@/components/ui/constants";

export function ModelPage() {
  const { data: metrics } = useQuery({ queryKey: ["modelMetrics"], queryFn: api.getModelMetrics });

  const metricCards = [
    { l: "F1 Score", v: metrics?.f1 ?? 0, icon: Zap },
    { l: "Precision", v: metrics?.precision ?? 0, icon: CheckCircle },
    { l: "Recall", v: metrics?.recall ?? 0, icon: Eye },
    { l: "PR-AUC", v: metrics?.average_precision ?? 0, icon: TrendingUp },
  ];

  const cm = metrics?.confusion_matrix;
  const cmTotal = cm ? cm.tp + cm.fp + cm.tn + cm.fn : 0;

  return (
    <div className="space-y-6">
      {/* Metric Cards */}
      <div className="grid grid-cols-4 gap-4">
        {metricCards.map(({ l, v, icon: Icon }) => (
          <div key={l} className="bg-white rounded-2xl p-5 border border-slate-100">
            <div className="flex items-center gap-2 mb-3">
              <Icon size={16} className="text-primary-500" />
              <span className="text-sm text-text-muted">{l}</span>
            </div>
            <div className="text-3xl font-bold text-slate-800">{v.toFixed(4)}</div>
            <div className="w-full h-1.5 bg-slate-100 rounded-full mt-3">
              <div className="h-full rounded-full transition-all duration-1000"
                style={{ width: `${v * 100}%`, background: `linear-gradient(90deg, ${HEX.primary}, ${HEX.violet})` }} />
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Threshold Sensitivity */}
        <div className="bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={BarChart3} title="閾值敏感度分析" subtitle="Threshold vs F1 / Precision / Recall" />
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={metrics?.threshold_sensitivity ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="threshold" tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} domain={[0, 1]} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }} />
              <Legend />
              <Line type="monotone" dataKey="f1" stroke={HEX.primary} strokeWidth={2} dot={false} name="F1" />
              <Line type="monotone" dataKey="precision" stroke={HEX.accent} strokeWidth={2} dot={false} name="Precision" />
              <Line type="monotone" dataKey="recall" stroke={HEX.warning} strokeWidth={2} dot={false} name="Recall" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Confusion Matrix */}
        <div className="bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={Grid3X3} title="混淆矩陣" subtitle="Confusion Matrix（交叉驗證結果）" />
          {cm ? (
            <div className="flex flex-col items-center justify-center h-[350px]">
              <div className="text-xs text-text-muted mb-3 self-center">模型預測 →</div>
              <div className="grid grid-cols-[auto_1fr_1fr] gap-0 text-center">
                {/* Header */}
                <div />
                <div className="px-4 py-2 text-xs font-semibold text-slate-500">預測陽性</div>
                <div className="px-4 py-2 text-xs font-semibold text-slate-500">預測陰性</div>

                {/* Row 1: Actual Positive */}
                <div className="px-4 py-6 text-xs font-semibold text-slate-500 flex items-center">實際<br/>陽性</div>
                <div className="px-4 py-6 rounded-tl-xl" style={{ background: "#DCFCE7" }}>
                  <div className="text-2xl font-bold" style={{ color: HEX.safe }}>{cm.tp.toLocaleString()}</div>
                  <div className="text-xs text-text-muted mt-1">TP ({(cm.tp / cmTotal * 100).toFixed(1)}%)</div>
                </div>
                <div className="px-4 py-6 rounded-tr-xl" style={{ background: "#FEE2E2" }}>
                  <div className="text-2xl font-bold" style={{ color: HEX.danger }}>{cm.fn.toLocaleString()}</div>
                  <div className="text-xs text-text-muted mt-1">FN ({(cm.fn / cmTotal * 100).toFixed(1)}%)</div>
                </div>

                {/* Row 2: Actual Negative */}
                <div className="px-4 py-6 text-xs font-semibold text-slate-500 flex items-center">實際<br/>陰性</div>
                <div className="px-4 py-6 rounded-bl-xl" style={{ background: "#FEF3C7" }}>
                  <div className="text-2xl font-bold" style={{ color: HEX.warning }}>{cm.fp.toLocaleString()}</div>
                  <div className="text-xs text-text-muted mt-1">FP ({(cm.fp / cmTotal * 100).toFixed(1)}%)</div>
                </div>
                <div className="px-4 py-6 rounded-br-xl" style={{ background: "#DBEAFE" }}>
                  <div className="text-2xl font-bold" style={{ color: HEX.primary }}>{cm.tn.toLocaleString()}</div>
                  <div className="text-xs text-text-muted mt-1">TN ({(cm.tn / cmTotal * 100).toFixed(1)}%)</div>
                </div>
              </div>
              <div className="text-xs text-text-muted mt-3">↑ 實際標籤</div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-[350px] text-text-faint text-sm">載入中...</div>
          )}
        </div>
      </div>
    </div>
  );
}
