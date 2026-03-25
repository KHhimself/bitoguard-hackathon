"use client";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  AreaChart, Area, CartesianGrid, XAxis, YAxis, Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Search, Wallet, Activity, Clock, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { RiskMeter } from "@/components/ui/RiskMeter";
import { SectionTitle } from "@/components/ui/SectionTitle";
import { C, HEX } from "@/components/ui/constants";

function normalizeFeature(value: unknown, max: number): number {
  const num = Number(value) || 0;
  return Math.min(Math.round((num / max) * 100), 100);
}

export function QueryPage({ initialId }: { initialId?: string }) {
  const [searchVal, setSearchVal] = useState(initialId || "");
  const [userId, setUserId] = useState(initialId || "");

  useEffect(() => {
    if (initialId) { setSearchVal(initialId); setUserId(initialId); }
  }, [initialId]);

  const { data: quickAlerts } = useQuery({
    queryKey: ["quickAlerts"],
    queryFn: () => api.getAlerts({ page_size: 3, risk_level: "critical" }),
  });

  const { data: user360, isLoading } = useQuery({
    queryKey: ["user360", userId],
    queryFn: () => api.getUser360(userId),
    enabled: !!userId,
  });

  const alertId = user360?.latest_prediction?.alert_id;
  const { data: report } = useQuery({
    queryKey: ["alertReport", alertId],
    queryFn: () => api.getAlertReport(alertId!),
    enabled: !!alertId,
  });

  const handleSearch = (val?: string) => {
    const q = val || searchVal;
    if (q.trim()) setUserId(q.trim());
  };

  const pred = user360?.latest_prediction;
  const score = Math.round(pred?.risk_score ?? 0);
  const riskLabel = score >= 80 ? "高風險" : score >= 50 ? "中風險" : "低風險";
  const riskVariant = score >= 80 ? "danger" as const : score >= 50 ? "warning" as const : "success" as const;

  const features = user360?.latest_features ?? {};
  const radarData = [
    { metric: "台幣流量", A: normalizeFeature(features["twd_total_sum"], 1_000_000) },
    { metric: "虛幣流量", A: normalizeFeature(features["crypto_total_sum"], 1_000_000) },
    { metric: "快速出金", A: normalizeFeature(features["fast_cashout_24h_count"], 15) },
    { metric: "交易頻率", A: normalizeFeature(features["twd_total_count"], 30) },
    { metric: "夜間交易", A: normalizeFeature(features["trade_night_ratio"], 1) },
    { metric: "內轉對手", A: normalizeFeature(features["relation_unique_counterparty_count"], 10) },
  ];

  const timeline = (report?.timeline_summary ?? []).map((t: { time: string; amount?: number }) => ({
    time: new Date(t.time).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" }),
    amount: t.amount ?? 0,
  }));

  const user = user360?.user ?? {};

  return (
    <div className="space-y-6">
      {/* Search Bar */}
      <div className="bg-white rounded-2xl p-8 border border-slate-100">
        <SectionTitle icon={Search} title="搜尋用戶" subtitle="輸入用戶 ID 查詢風險評分" />
        <div className="flex gap-3 mt-4">
          <div className="flex-1 relative">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300" />
            <input
              type="text" value={searchVal}
              onChange={(e) => setSearchVal(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="輸入 User ID..."
              className="w-full pl-11 pr-4 py-3.5 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-400 transition"
            />
          </div>
          <button onClick={() => handleSearch()}
            className="px-8 py-3.5 rounded-xl text-white font-medium text-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0"
            style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
            {isLoading ? <RefreshCw size={16} className="animate-spin" /> : "查詢"}
          </button>
        </div>
        <div className="flex gap-2 mt-3">
          {(quickAlerts?.items ?? []).map((a: { alert_id: string; user_id: string }) => (
            <button key={a.alert_id} onClick={() => { setSearchVal(a.user_id); handleSearch(a.user_id); }}
              className="px-3 py-1.5 text-xs rounded-lg bg-slate-50 text-slate-500 hover:bg-blue-50 hover:text-blue-600 transition border border-slate-100">
              {a.user_id}
            </button>
          ))}
        </div>
      </div>

      {/* Result */}
      {user360 && (
        <div className="grid grid-cols-3 gap-4" style={{ animation: "fadeIn 0.5s ease" }}>
          {/* Risk Score */}
          <div className="bg-white rounded-2xl p-8 border border-slate-100 flex flex-col items-center justify-center">
            <RiskMeter score={score} size="lg" />
            <div className="mt-4 text-center">
              <Badge variant={riskVariant}>{riskLabel}</Badge>
              <div className="text-xs text-text-muted mt-2">綜合風險評分</div>
            </div>
          </div>

          {/* User Info */}
          <div className="bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Wallet} title="用戶資訊" />
            <div className="space-y-3 mt-2">
              {[
                { l: "用戶 ID", v: String(user["user_id"] ?? userId) },
                { l: "性別 / 年齡", v: `${user["sex_label"] ?? "—"} / ${user["age"] ?? "—"} 歲` },
                { l: "職業", v: String(user["career_label"] ?? "—") },
                { l: "KYC 等級", v: `Level ${user["kyc_level"] ?? "—"}` },
                { l: "註冊日期", v: user["confirmed_at"] ? new Date(String(user["confirmed_at"])).toLocaleDateString("zh-TW") : "—" },
                { l: "註冊來源", v: String(user["user_source_label"] ?? "—") },
                { l: "黑名單", v: user["is_known_blacklist"] ? "是" : "否", highlight: !!user["is_known_blacklist"] },
              ].map(({ l, v, highlight }) => (
                <div key={l} className="flex justify-between items-center py-1.5 border-b border-slate-50 last:border-0">
                  <span className="text-sm text-text-muted">{l}</span>
                  <span className={`text-sm font-medium ${highlight ? "text-red-500" : "text-slate-700"}`}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Radar */}
          <div className="bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Activity} title="風險雷達" />
            <ResponsiveContainer width="100%" height={250}>
              <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="65%">
                <PolarGrid stroke="#E8ECF2" />
                <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11, fill: "#64748B" }} />
                <PolarRadiusAxis tick={false} axisLine={false} domain={[0, 100]} />
                <Radar dataKey="A" stroke={HEX.primary} fill={HEX.primary} fillOpacity={0.15} strokeWidth={2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Transaction Timeline */}
          <div className="col-span-3 bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Clock} title="交易時序" subtitle="近期交易金額分布" />
            {timeline.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={timeline}>
                  <defs>
                    <linearGradient id="txGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={HEX.primary} stopOpacity={0.15} />
                      <stop offset="95%" stopColor={HEX.primary} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }} />
                  <Area type="monotone" dataKey="amount" stroke={HEX.primary} fill="url(#txGrad)" strokeWidth={2} name="交易金額" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[200px] text-text-faint text-sm">無交易時序資料</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
