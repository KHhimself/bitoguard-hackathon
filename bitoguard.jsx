import { useState, useEffect, useRef, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  AreaChart, Area
} from "recharts";
import {
  Shield, Search, Network, Brain, ChevronRight, AlertTriangle,
  TrendingUp, Users, Activity, ArrowUpRight, ArrowDownRight,
  Eye, Clock, Zap, Database, Filter, Download, Bell,
  CheckCircle, XCircle, BarChart3, GitBranch, Layers,
  Hash, Wallet, ArrowRight, Info, ExternalLink, RefreshCw
} from "lucide-react";
import * as d3 from "d3";

// ─── Color Palette ───
const C = {
  primary: "#0F62FE",
  primaryLight: "#D0E2FF",
  accent: "#00C9A7",
  danger: "#FF3B5C",
  warning: "#FFB020",
  safe: "#24D164",
  bg: "#F7F9FC",
  card: "#FFFFFF",
  text: "#1A1A2E",
  muted: "#6B7A99",
  border: "#E8ECF2",
  gradientA: "#0F62FE",
  gradientB: "#7B61FF",
};

// ─── Mock Data ───
const STATS = {
  totalUsers: 24_837,
  flagged: 1_243,
  highRisk: 387,
  modelF1: 0.3629,
  precision: 0.412,
  recall: 0.324,
  auc: 0.891,
};

const RISK_DIST = [
  { range: "0-10", count: 8420, fill: "#24D164" },
  { range: "10-20", count: 5230, fill: "#24D164" },
  { range: "20-30", count: 3840, fill: "#7CE08A" },
  { range: "30-40", count: 2670, fill: "#FFE066" },
  { range: "40-50", count: 1890, fill: "#FFB020" },
  { range: "50-60", count: 1120, fill: "#FF9A3C" },
  { range: "60-70", count: 740, fill: "#FF6B4A" },
  { range: "70-80", count: 480, fill: "#FF3B5C" },
  { range: "80-90", count: 290, fill: "#E01E5A" },
  { range: "90-100", count: 157, fill: "#B5144A" },
];

const ALERTS_TIMELINE = Array.from({ length: 30 }, (_, i) => ({
  day: `3/${i + 1}`,
  alerts: Math.floor(Math.random() * 40 + 10),
  resolved: Math.floor(Math.random() * 30 + 5),
}));

const RECENT_ALERTS = [
  { id: "USR-4821", risk: 94, type: "分層轉帳", time: "2 分鐘前", status: "pending" },
  { id: "USR-7293", risk: 87, type: "快速提領", time: "8 分鐘前", status: "pending" },
  { id: "USR-1057", risk: 82, type: "黑名單關聯", time: "15 分鐘前", status: "reviewing" },
  { id: "USR-3394", risk: 76, type: "異常交易模式", time: "22 分鐘前", status: "reviewing" },
  { id: "USR-6618", risk: 71, type: "新帳戶大額交易", time: "31 分鐘前", status: "resolved" },
];

const MODEL_FEATURES = [
  { name: "blacklist_hop_dist", importance: 0.182, display: "黑名單跳數距離" },
  { name: "tx_velocity_7d", importance: 0.156, display: "7日交易速率" },
  { name: "amt_std_ratio", importance: 0.134, display: "金額標準差比率" },
  { name: "in_out_degree_ratio", importance: 0.121, display: "入出度比率" },
  { name: "pagerank_score", importance: 0.098, display: "PageRank 分數" },
  { name: "acct_age_days", importance: 0.087, display: "帳戶天數" },
  { name: "unique_counterparty", importance: 0.076, display: "唯一交易對手數" },
  { name: "avg_tx_interval", importance: 0.065, display: "平均交易間隔" },
  { name: "max_single_tx", importance: 0.054, display: "單筆最大交易額" },
  { name: "night_tx_ratio", importance: 0.027, display: "夜間交易比率" },
];

const SHAP_WATERFALL = [
  { feature: "黑名單跳數", value: 0.23, direction: "pos" },
  { feature: "7日交易速率", value: 0.18, direction: "pos" },
  { feature: "金額標準差", value: 0.12, direction: "pos" },
  { feature: "入出度比率", value: 0.09, direction: "pos" },
  { feature: "帳戶天數", value: -0.14, direction: "neg" },
  { feature: "PageRank", value: 0.07, direction: "pos" },
  { feature: "交易間隔", value: -0.06, direction: "neg" },
  { feature: "夜間比率", value: 0.04, direction: "pos" },
];

const RADAR_DATA = [
  { metric: "交易速率", A: 85, fullMark: 100 },
  { metric: "金額異常", A: 72, fullMark: 100 },
  { metric: "圖譜風險", A: 91, fullMark: 100 },
  { metric: "時序異常", A: 58, fullMark: 100 },
  { metric: "帳戶特徵", A: 43, fullMark: 100 },
  { metric: "對手風險", A: 67, fullMark: 100 },
];

const MOCK_USERS = {
  "USR-4821": { name: "0x7a3B...f29E", risk: 94, label: "suspicious", txCount: 342, totalAmt: "1,247,800 USDT", joined: "2025-11-03", lastTx: "2 分鐘前" },
  "USR-7293": { name: "0x1dC8...a47B", risk: 87, label: "suspicious", txCount: 128, totalAmt: "892,350 USDT", joined: "2025-12-15", lastTx: "8 分鐘前" },
  "USR-1057": { name: "0x9eF2...c83D", risk: 82, label: "suspicious", txCount: 89, totalAmt: "543,200 USDT", joined: "2026-01-22", lastTx: "15 分鐘前" },
  "default": { name: "0xAb3F...d91C", risk: 45, label: "normal", txCount: 56, totalAmt: "128,400 USDT", joined: "2025-08-10", lastTx: "1 小時前" },
};

// ─── Graph Data for D3 ───
const GRAPH_NODES = [
  { id: "USR-4821", risk: 94, type: "flagged", group: 1 },
  { id: "USR-7293", risk: 87, type: "flagged", group: 1 },
  { id: "USR-1057", risk: 82, type: "flagged", group: 2 },
  { id: "A-001", risk: 35, type: "normal", group: 1 },
  { id: "A-002", risk: 22, type: "normal", group: 1 },
  { id: "A-003", risk: 48, type: "normal", group: 2 },
  { id: "A-004", risk: 15, type: "normal", group: 2 },
  { id: "BL-001", risk: 100, type: "blacklist", group: 3 },
  { id: "BL-002", risk: 100, type: "blacklist", group: 3 },
  { id: "A-005", risk: 60, type: "normal", group: 3 },
  { id: "A-006", risk: 28, type: "normal", group: 1 },
  { id: "A-007", risk: 55, type: "normal", group: 2 },
  { id: "EX-001", risk: 10, type: "exchange", group: 1 },
  { id: "EX-002", risk: 10, type: "exchange", group: 2 },
];

const GRAPH_LINKS = [
  { source: "USR-4821", target: "A-001", value: 50000 },
  { source: "USR-4821", target: "A-002", value: 32000 },
  { source: "USR-4821", target: "BL-001", value: 120000 },
  { source: "A-001", target: "USR-7293", value: 28000 },
  { source: "USR-7293", target: "A-006", value: 45000 },
  { source: "USR-7293", target: "EX-001", value: 89000 },
  { source: "USR-1057", target: "A-003", value: 37000 },
  { source: "USR-1057", target: "A-007", value: 22000 },
  { source: "A-003", target: "BL-002", value: 67000 },
  { source: "A-004", target: "USR-1057", value: 18000 },
  { source: "BL-001", target: "A-005", value: 95000 },
  { source: "A-005", target: "A-002", value: 41000 },
  { source: "A-006", target: "EX-001", value: 33000 },
  { source: "A-007", target: "EX-002", value: 56000 },
  { source: "A-004", target: "EX-002", value: 12000 },
];

// ─── Utility Components ───
const Badge = ({ children, variant = "default" }) => {
  const styles = {
    default: "bg-slate-100 text-slate-600",
    danger: "bg-red-50 text-red-600",
    warning: "bg-amber-50 text-amber-600",
    success: "bg-emerald-50 text-emerald-600",
    info: "bg-blue-50 text-blue-600",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[variant]}`}>
      {children}
    </span>
  );
};

const RiskMeter = ({ score, size = "lg" }) => {
  const getColor = (s) => s >= 80 ? C.danger : s >= 60 ? C.warning : s >= 40 ? "#FFE066" : C.safe;
  const circumference = size === "lg" ? 2 * Math.PI * 54 : 2 * Math.PI * 36;
  const r = size === "lg" ? 54 : 36;
  const dim = size === "lg" ? 140 : 96;
  const stroke = size === "lg" ? 10 : 7;
  const fontSize = size === "lg" ? "text-3xl" : "text-xl";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: dim, height: dim }}>
      <svg width={dim} height={dim} className="-rotate-90">
        <circle cx={dim/2} cy={dim/2} r={r} fill="none" stroke="#E8ECF2" strokeWidth={stroke} />
        <circle
          cx={dim/2} cy={dim/2} r={r} fill="none"
          stroke={getColor(score)} strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease" }}
        />
      </svg>
      <span className={`absolute ${fontSize} font-bold`} style={{ color: getColor(score) }}>{score}</span>
    </div>
  );
};

const StatCard = ({ icon: Icon, label, value, change, changeType }) => (
  <div className="bg-white rounded-2xl p-5 border border-slate-100 hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5">
    <div className="flex items-center justify-between mb-3">
      <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: C.primaryLight }}>
        <Icon size={20} style={{ color: C.primary }} />
      </div>
      {change && (
        <div className={`flex items-center gap-1 text-xs font-medium ${changeType === "up" ? "text-emerald-500" : "text-red-500"}`}>
          {changeType === "up" ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
          {change}
        </div>
      )}
    </div>
    <div className="text-2xl font-bold text-slate-800">{typeof value === "number" ? value.toLocaleString() : value}</div>
    <div className="text-sm text-slate-400 mt-1">{label}</div>
  </div>
);

const SectionTitle = ({ icon: Icon, title, subtitle }) => (
  <div className="mb-6">
    <div className="flex items-center gap-2.5 mb-1">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
        <Icon size={16} color="white" />
      </div>
      <h2 className="text-xl font-bold text-slate-800">{title}</h2>
    </div>
    {subtitle && <p className="text-sm text-slate-400 ml-10">{subtitle}</p>}
  </div>
);

// ─── Navigation ───
const NAV_ITEMS = [
  { key: "dashboard", icon: BarChart3, label: "Dashboard" },
  { key: "query", icon: Search, label: "風險查詢" },
  { key: "graph", icon: Network, label: "交易圖譜" },
  { key: "model", icon: Brain, label: "模型解釋" },
];

const Sidebar = ({ active, setActive }) => (
  <div className="w-64 bg-white border-r border-slate-100 flex flex-col h-full fixed left-0 top-0 z-50">
    <div className="p-6 border-b border-slate-100">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
          <Shield size={22} color="white" />
        </div>
        <div>
          <div className="text-lg font-bold text-slate-800 tracking-tight">BitoGuard</div>
          <div className="text-xs text-slate-400 font-medium">AML Risk Platform</div>
        </div>
      </div>
    </div>
    <nav className="flex-1 p-4 space-y-1.5">
      {NAV_ITEMS.map(({ key, icon: Icon, label }) => (
        <button
          key={key}
          onClick={() => setActive(key)}
          className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
            active === key
              ? "bg-blue-50 text-blue-600 shadow-sm"
              : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
          }`}
        >
          <Icon size={18} />
          {label}
        </button>
      ))}
    </nav>
    <div className="p-4 mx-4 mb-4 rounded-xl border border-dashed border-slate-200 bg-slate-50">
      <div className="flex items-center gap-2 mb-2">
        <Zap size={14} className="text-amber-500" />
        <span className="text-xs font-semibold text-slate-600">Model Status</span>
      </div>
      <div className="text-xs text-slate-400">
        <div className="flex justify-between mb-1"><span>Ensemble v3.2</span><span className="text-emerald-500">● Online</span></div>
        <div className="flex justify-between"><span>Last updated</span><span>10 min ago</span></div>
      </div>
    </div>
  </div>
);

const TopBar = ({ page }) => {
  const titles = {
    dashboard: "風險總覽 Dashboard",
    query: "用戶風險查詢",
    graph: "交易圖譜視覺化",
    model: "模型解釋性分析",
  };
  return (
    <div className="h-16 bg-white border-b border-slate-100 flex items-center justify-between px-8 sticky top-0 z-40">
      <h1 className="text-lg font-semibold text-slate-700">{titles[page]}</h1>
      <div className="flex items-center gap-3">
        <button className="relative p-2 rounded-lg hover:bg-slate-50 transition">
          <Bell size={18} className="text-slate-400" />
          <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
        </button>
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white" style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
          BG
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════
// PAGE 1: Dashboard
// ═══════════════════════════════════════
const DashboardPage = ({ setActive, setQueryId }) => {
  const handleAlertClick = (id) => {
    setQueryId(id);
    setActive("query");
  };

  return (
    <div className="space-y-6">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={Users} label="總用戶數" value={STATS.totalUsers} change="+3.2%" changeType="up" />
        <StatCard icon={AlertTriangle} label="標記帳戶" value={STATS.flagged} change="+12" changeType="up" />
        <StatCard icon={Shield} label="高風險用戶" value={STATS.highRisk} change="-5" changeType="down" />
        <StatCard icon={Activity} label="模型 AUC" value={STATS.auc.toFixed(3)} />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Risk Distribution */}
        <div className="col-span-2 bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={BarChart3} title="風險分數分布" subtitle="全體用戶風險分數直方圖" />
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={RISK_DIST} barCategoryGap="12%">
              <XAxis dataKey="range" tick={{ fontSize: 12, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }}
                formatter={(v) => [v.toLocaleString(), "用戶數"]}
              />
              {RISK_DIST.map((entry, i) => (
                <Bar key={i} dataKey="count" radius={[6, 6, 0, 0]}>
                  {RISK_DIST.map((e, j) => <Cell key={j} fill={e.fill} />)}
                </Bar>
              )).slice(0, 1)}
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Risk Pie */}
        <div className="bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={Layers} title="風險等級" subtitle="用戶分級佔比" />
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={[
                  { name: "低風險", value: 68, fill: C.safe },
                  { name: "中風險", value: 22, fill: C.warning },
                  { name: "高風險", value: 10, fill: C.danger },
                ]}
                cx="50%" cy="50%" innerRadius={50} outerRadius={75}
                paddingAngle={4} dataKey="value" strokeWidth={0}
              >
                {[C.safe, C.warning, C.danger].map((c, i) => <Cell key={i} fill={c} />)}
              </Pie>
              <Tooltip formatter={(v) => [`${v}%`, "佔比"]} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 mt-2">
            {[{ c: C.safe, l: "低風險" }, { c: C.warning, l: "中風險" }, { c: C.danger, l: "高風險" }].map(({ c, l }) => (
              <div key={l} className="flex items-center gap-1.5 text-xs text-slate-500">
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Timeline + Alerts */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={TrendingUp} title="警報趨勢" subtitle="近 30 天警報與解決數量" />
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={ALERTS_TIMELINE}>
              <defs>
                <linearGradient id="alertGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={C.danger} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={C.danger} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="resolvedGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={C.safe} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={C.safe} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }} />
              <Area type="monotone" dataKey="alerts" stroke={C.danger} fill="url(#alertGrad)" strokeWidth={2} name="警報" />
              <Area type="monotone" dataKey="resolved" stroke={C.safe} fill="url(#resolvedGrad)" strokeWidth={2} name="已解決" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Recent Alerts */}
        <div className="bg-white rounded-2xl p-6 border border-slate-100">
          <SectionTitle icon={Bell} title="即時警報" />
          <div className="space-y-3">
            {RECENT_ALERTS.map((a) => (
              <button
                key={a.id}
                onClick={() => handleAlertClick(a.id)}
                className="w-full flex items-center justify-between p-3 rounded-xl hover:bg-slate-50 transition group text-left"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${a.risk >= 80 ? "bg-red-500 animate-pulse" : "bg-amber-400"}`} />
                  <div>
                    <div className="text-sm font-medium text-slate-700">{a.id}</div>
                    <div className="text-xs text-slate-400">{a.type} · {a.time}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold ${a.risk >= 80 ? "text-red-500" : "text-amber-500"}`}>{a.risk}</span>
                  <ChevronRight size={14} className="text-slate-300 group-hover:text-slate-500 transition" />
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════
// PAGE 2: Risk Query
// ═══════════════════════════════════════
const QueryPage = ({ initialId }) => {
  const [searchVal, setSearchVal] = useState(initialId || "");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (initialId) handleSearch(initialId);
  }, [initialId]);

  const handleSearch = (val) => {
    const q = val || searchVal;
    if (!q.trim()) return;
    setLoading(true);
    setTimeout(() => {
      setResult(MOCK_USERS[q] || MOCK_USERS["default"]);
      setLoading(false);
    }, 800);
  };

  const getRiskLabel = (r) => r >= 80 ? "高風險" : r >= 50 ? "中風險" : "低風險";
  const getRiskVariant = (r) => r >= 80 ? "danger" : r >= 50 ? "warning" : "success";

  return (
    <div className="space-y-6">
      {/* Search Bar */}
      <div className="bg-white rounded-2xl p-8 border border-slate-100">
        <SectionTitle icon={Search} title="搜尋用戶" subtitle="輸入用戶 ID 或錢包地址查詢風險評分" />
        <div className="flex gap-3 mt-4">
          <div className="flex-1 relative">
            <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300" />
            <input
              type="text"
              value={searchVal}
              onChange={(e) => setSearchVal(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="輸入 USR-XXXX 或 0x 地址..."
              className="w-full pl-11 pr-4 py-3.5 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-400 transition"
            />
          </div>
          <button
            onClick={() => handleSearch()}
            className="px-8 py-3.5 rounded-xl text-white font-medium text-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0"
            style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}
          >
            {loading ? <RefreshCw size={16} className="animate-spin" /> : "查詢"}
          </button>
        </div>
        <div className="flex gap-2 mt-3">
          {["USR-4821", "USR-7293", "USR-1057"].map((id) => (
            <button
              key={id}
              onClick={() => { setSearchVal(id); handleSearch(id); }}
              className="px-3 py-1.5 text-xs rounded-lg bg-slate-50 text-slate-500 hover:bg-blue-50 hover:text-blue-600 transition border border-slate-100"
            >
              {id}
            </button>
          ))}
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className="grid grid-cols-3 gap-4" style={{ animation: "fadeIn 0.5s ease" }}>
          {/* Risk Score Card */}
          <div className="bg-white rounded-2xl p-8 border border-slate-100 flex flex-col items-center justify-center">
            <RiskMeter score={result.risk} size="lg" />
            <div className="mt-4 text-center">
              <Badge variant={getRiskVariant(result.risk)}>{getRiskLabel(result.risk)}</Badge>
              <div className="text-xs text-slate-400 mt-2">綜合風險評分</div>
            </div>
          </div>

          {/* User Info */}
          <div className="bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Wallet} title="用戶資訊" />
            <div className="space-y-4 mt-2">
              {[
                { l: "錢包地址", v: result.name },
                { l: "交易筆數", v: result.txCount },
                { l: "總交易金額", v: result.totalAmt },
                { l: "註冊日期", v: result.joined },
                { l: "最近交易", v: result.lastTx },
              ].map(({ l, v }) => (
                <div key={l} className="flex justify-between items-center py-1.5 border-b border-slate-50 last:border-0">
                  <span className="text-sm text-slate-400">{l}</span>
                  <span className="text-sm font-medium text-slate-700">{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Radar */}
          <div className="bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Activity} title="風險雷達" />
            <ResponsiveContainer width="100%" height={230}>
              <RadarChart data={RADAR_DATA}>
                <PolarGrid stroke="#E8ECF2" />
                <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11, fill: "#6B7A99" }} />
                <PolarRadiusAxis tick={false} axisLine={false} />
                <Radar
                  dataKey="A" stroke={C.primary} fill={C.primary}
                  fillOpacity={0.15} strokeWidth={2}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Transaction Timeline */}
          <div className="col-span-3 bg-white rounded-2xl p-6 border border-slate-100">
            <SectionTitle icon={Clock} title="交易時序" subtitle="近期交易金額分布" />
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={Array.from({ length: 20 }, (_, i) => ({
                time: `T-${20 - i}`,
                amount: Math.floor(Math.random() * 80000 + 5000),
                avg: 35000,
              }))}>
                <defs>
                  <linearGradient id="txGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={C.primary} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={C.primary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }} formatter={(v) => [`${(v/1000).toFixed(1)}K USDT`]} />
                <Area type="monotone" dataKey="amount" stroke={C.primary} fill="url(#txGrad)" strokeWidth={2} name="交易金額" />
                <Line type="monotone" dataKey="avg" stroke={C.muted} strokeDasharray="5 5" strokeWidth={1.5} dot={false} name="平均" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════
// PAGE 3: Transaction Graph
// ═══════════════════════════════════════
const GraphPage = () => {
  const svgRef = useRef(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (!svgRef.current || initialized) return;
    setInitialized(true);

    const container = svgRef.current.parentElement;
    const width = container.clientWidth;
    const height = 500;

    const svg = d3.select(svgRef.current)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", [0, 0, width, height]);

    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    defs.append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "-0 -5 10 10")
      .attr("refX", 25)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M 0,-5 L 10,0 L 0,5")
      .attr("fill", "#CBD5E1");

    const nodes = GRAPH_NODES.map(d => ({ ...d }));
    const links = GRAPH_LINKS.map(d => ({ ...d }));

    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(d => d.id).distance(100))
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30));

    const linkGroup = svg.append("g");
    const nodeGroup = svg.append("g");
    const labelGroup = svg.append("g");

    const link = linkGroup.selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "#E2E8F0")
      .attr("stroke-width", d => Math.max(1, d.value / 30000))
      .attr("marker-end", "url(#arrowhead)")
      .attr("opacity", 0.7);

    const getNodeColor = (d) => {
      if (d.type === "blacklist") return C.danger;
      if (d.type === "flagged") return C.warning;
      if (d.type === "exchange") return C.primary;
      return d.risk > 50 ? "#FFB86C" : C.safe;
    };

    const getNodeRadius = (d) => {
      if (d.type === "blacklist") return 16;
      if (d.type === "flagged") return 14;
      if (d.type === "exchange") return 12;
      return 10;
    };

    const node = nodeGroup.selectAll("circle")
      .data(nodes)
      .join("circle")
      .attr("r", getNodeRadius)
      .attr("fill", getNodeColor)
      .attr("stroke", "white")
      .attr("stroke-width", 2.5)
      .attr("cursor", "pointer")
      .attr("filter", "drop-shadow(0 2px 4px rgba(0,0,0,0.1))")
      .on("mouseover", function(event, d) {
        d3.select(this).transition().duration(200).attr("r", getNodeRadius(d) + 4);
        setHoveredNode(d);
      })
      .on("mouseout", function(event, d) {
        d3.select(this).transition().duration(200).attr("r", getNodeRadius(d));
        setHoveredNode(null);
      })
      .call(d3.drag()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );

    const label = labelGroup.selectAll("text")
      .data(nodes)
      .join("text")
      .text(d => d.id)
      .attr("font-size", 9)
      .attr("fill", "#64748B")
      .attr("text-anchor", "middle")
      .attr("dy", d => getNodeRadius(d) + 14)
      .attr("font-family", "monospace")
      .attr("pointer-events", "none");

    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("cx", d => d.x).attr("cy", d => d.y);
      label.attr("x", d => d.x).attr("y", d => d.y);
    });
  }, [initialized]);

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl p-6 border border-slate-100">
        <div className="flex items-center justify-between mb-4">
          <SectionTitle icon={Network} title="交易關聯圖譜" subtitle="力導向圖 — 節點可拖曳互動" />
          <div className="flex gap-4">
            {[
              { c: C.danger, l: "黑名單" },
              { c: C.warning, l: "標記用戶" },
              { c: C.primary, l: "交易所" },
              { c: C.safe, l: "一般用戶" },
            ].map(({ c, l }) => (
              <div key={l} className="flex items-center gap-1.5 text-xs text-slate-500">
                <div className="w-3 h-3 rounded-full" style={{ background: c }} />{l}
              </div>
            ))}
          </div>
        </div>

        <div className="relative rounded-xl bg-slate-50 border border-slate-100 overflow-hidden">
          <svg ref={svgRef} />
          {hoveredNode && (
            <div className="absolute top-4 right-4 bg-white rounded-xl p-4 shadow-lg border border-slate-100 min-w-48"
              style={{ animation: "fadeIn 0.2s ease" }}>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-3 h-3 rounded-full" style={{ background: hoveredNode.type === "blacklist" ? C.danger : hoveredNode.type === "flagged" ? C.warning : C.safe }} />
                <span className="text-sm font-bold text-slate-700">{hoveredNode.id}</span>
              </div>
              <div className="space-y-1 text-xs text-slate-500">
                <div className="flex justify-between"><span>風險分數</span><span className="font-medium text-slate-700">{hoveredNode.risk}</span></div>
                <div className="flex justify-between"><span>類型</span>
                  <Badge variant={hoveredNode.type === "blacklist" ? "danger" : hoveredNode.type === "flagged" ? "warning" : "success"}>
                    {hoveredNode.type === "blacklist" ? "黑名單" : hoveredNode.type === "flagged" ? "標記" : hoveredNode.type === "exchange" ? "交易所" : "一般"}
                  </Badge>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Edge Info */}
      <div className="bg-white rounded-2xl p-6 border border-slate-100">
        <SectionTitle icon={GitBranch} title="交易鏈路摘要" subtitle="主要資金流動路徑" />
        <div className="grid grid-cols-2 gap-3 mt-4">
          {GRAPH_LINKS.slice(0, 6).map((l, i) => (
            <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-100">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-mono text-xs bg-white px-2 py-1 rounded-lg border border-slate-100">{typeof l.source === 'object' ? l.source.id : l.source}</span>
                <ArrowRight size={14} className="text-slate-300" />
                <span className="font-mono text-xs bg-white px-2 py-1 rounded-lg border border-slate-100">{typeof l.target === 'object' ? l.target.id : l.target}</span>
              </div>
              <span className="text-sm font-medium text-slate-600">{(l.value / 1000).toFixed(0)}K USDT</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════
// PAGE 4: Model Explainability
// ═══════════════════════════════════════
const ModelPage = () => (
  <div className="space-y-6">
    {/* Model Metrics */}
    <div className="grid grid-cols-4 gap-4">
      {[
        { l: "F1 Score", v: STATS.modelF1, icon: Zap },
        { l: "Precision", v: STATS.precision, icon: CheckCircle },
        { l: "Recall", v: STATS.recall, icon: Eye },
        { l: "AUC-ROC", v: STATS.auc, icon: TrendingUp },
      ].map(({ l, v, icon: Icon }) => (
        <div key={l} className="bg-white rounded-2xl p-5 border border-slate-100">
          <div className="flex items-center gap-2 mb-3">
            <Icon size={16} style={{ color: C.primary }} />
            <span className="text-sm text-slate-400">{l}</span>
          </div>
          <div className="text-3xl font-bold text-slate-800">{v.toFixed(4)}</div>
          <div className="w-full h-1.5 bg-slate-100 rounded-full mt-3">
            <div className="h-full rounded-full transition-all duration-1000"
              style={{ width: `${v * 100}%`, background: `linear-gradient(90deg, ${C.gradientA}, ${C.gradientB})` }} />
          </div>
        </div>
      ))}
    </div>

    <div className="grid grid-cols-2 gap-4">
      {/* Feature Importance */}
      <div className="bg-white rounded-2xl p-6 border border-slate-100">
        <SectionTitle icon={BarChart3} title="特徵重要性排名" subtitle="Global Feature Importance (Top 10)" />
        <div className="space-y-3 mt-4">
          {MODEL_FEATURES.map((f, i) => (
            <div key={f.name} className="flex items-center gap-3">
              <span className="text-xs text-slate-400 w-4 text-right">{i + 1}</span>
              <span className="text-xs text-slate-600 w-32 truncate">{f.display}</span>
              <div className="flex-1 h-6 bg-slate-50 rounded-lg overflow-hidden relative">
                <div
                  className="h-full rounded-lg transition-all duration-1000"
                  style={{
                    width: `${(f.importance / MODEL_FEATURES[0].importance) * 100}%`,
                    background: `linear-gradient(90deg, ${C.primary}${i < 3 ? "" : "80"}, ${C.gradientB}${i < 3 ? "" : "60"})`,
                  }}
                />
                <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-500">
                  {(f.importance * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* SHAP Waterfall */}
      <div className="bg-white rounded-2xl p-6 border border-slate-100">
        <SectionTitle icon={Brain} title="SHAP 瀑布圖" subtitle="單一用戶 (USR-4821) 的特徵貢獻" />
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={SHAP_WATERFALL} layout="vertical" margin={{ left: 80 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: "#6B7A99" }} axisLine={false} tickLine={false} />
            <YAxis dataKey="feature" type="category" tick={{ fontSize: 12, fill: "#6B7A99" }} axisLine={false} tickLine={false} width={80} />
            <Tooltip
              contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }}
              formatter={(v) => [v > 0 ? `+${v.toFixed(3)}` : v.toFixed(3), "SHAP 值"]}
            />
            <Bar dataKey="value" radius={[0, 6, 6, 0]}>
              {SHAP_WATERFALL.map((entry, i) => (
                <Cell key={i} fill={entry.direction === "pos" ? C.danger : C.safe} opacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="flex justify-center gap-6 mt-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <div className="w-3 h-3 rounded" style={{ background: C.danger, opacity: 0.85 }} />推高風險
          </div>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <div className="w-3 h-3 rounded" style={{ background: C.safe, opacity: 0.85 }} />降低風險
          </div>
        </div>
      </div>
    </div>

    {/* Ensemble Architecture */}
    <div className="bg-white rounded-2xl p-6 border border-slate-100">
      <SectionTitle icon={Layers} title="模型架構" subtitle="Three-base Ensemble + Logistic Stacker" />
      <div className="flex items-center justify-center gap-4 py-8">
        {[
          { name: "GraphSAGE", desc: "GNN 圖特徵", color: C.primary },
          { name: "LightGBM", desc: "表格特徵", color: C.accent },
          { name: "XGBoost", desc: "交叉特徵", color: C.gradientB },
        ].map((m, i) => (
          <div key={m.name} className="flex items-center gap-4">
            <div className="text-center">
              <div className="w-28 h-28 rounded-2xl border-2 flex flex-col items-center justify-center transition-all hover:shadow-lg hover:-translate-y-1"
                style={{ borderColor: m.color, background: `${m.color}08` }}>
                <Database size={24} style={{ color: m.color }} />
                <div className="text-sm font-bold mt-2" style={{ color: m.color }}>{m.name}</div>
                <div className="text-xs text-slate-400">{m.desc}</div>
              </div>
            </div>
            {i < 2 && <div className="text-slate-300 text-2xl font-light">+</div>}
          </div>
        ))}
        <ArrowRight size={24} className="text-slate-300 mx-2" />
        <div className="w-36 h-28 rounded-2xl border-2 flex flex-col items-center justify-center"
          style={{ borderColor: C.danger, background: `${C.danger}08` }}>
          <Zap size={24} style={{ color: C.danger }} />
          <div className="text-sm font-bold mt-2" style={{ color: C.danger }}>Logistic Stacker</div>
          <div className="text-xs text-slate-400">最終預測</div>
        </div>
      </div>
    </div>
  </div>
);

// ═══════════════════════════════════════
// Main App
// ═══════════════════════════════════════
export default function App() {
  const [activePage, setActivePage] = useState("dashboard");
  const [queryId, setQueryId] = useState("");

  const handleSetActive = (page) => {
    setActivePage(page);
    if (page !== "query") setQueryId("");
  };

  return (
    <div className="flex min-h-screen" style={{ background: C.bg, fontFamily: "'DM Sans', 'Noto Sans TC', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=Noto+Sans+TC:wght@300;400;500;600;700&display=swap');
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 3px; }
      `}</style>
      <Sidebar active={activePage} setActive={handleSetActive} />
      <div className="flex-1 ml-64">
        <TopBar page={activePage} />
        <main className="p-8" style={{ animation: "fadeIn 0.4s ease" }}>
          {activePage === "dashboard" && <DashboardPage setActive={handleSetActive} setQueryId={setQueryId} />}
          {activePage === "query" && <QueryPage initialId={queryId} />}
          {activePage === "graph" && <GraphPage />}
          {activePage === "model" && <ModelPage />}
        </main>
      </div>
    </div>
  );
}
