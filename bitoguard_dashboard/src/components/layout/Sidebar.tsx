"use client";
import { BarChart3, Search, Network, Brain, Shield } from "lucide-react";
import { C } from "@/components/ui/constants";

const NAV_ITEMS = [
  { key: "dashboard", icon: BarChart3, label: "Dashboard" },
  { key: "query", icon: Search, label: "風險查詢" },
  { key: "graph", icon: Network, label: "交易圖譜" },
  { key: "model", icon: Brain, label: "模型解釋" },
];

export function Sidebar({ active, setActive }: { active: string; setActive: (key: string) => void }) {
  return (
    <div className="w-64 bg-white border-r border-slate-100 flex flex-col h-full fixed left-0 top-0 z-50">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
            <Shield size={22} color="white" />
          </div>
          <div>
            <div className="text-lg font-bold text-slate-800 tracking-tight">BitoGuard</div>
            <div className="text-xs text-text-muted font-medium">AML Risk Platform</div>
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
    </div>
  );
}
