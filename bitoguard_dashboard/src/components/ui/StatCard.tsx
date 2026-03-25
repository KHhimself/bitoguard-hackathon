import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
export function StatCard({ icon: Icon, label, value, change, changeType }: {
  icon: LucideIcon; label: string; value: string | number; change?: string; changeType?: "up" | "down";
}) {
  return (
    <div className="bg-white rounded-2xl p-5 border border-slate-100 hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5">
      <div className="flex items-center justify-between mb-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-primary-100">
          <Icon size={20} className="text-primary-500" />
        </div>
        {change && (
          <div className={`flex items-center gap-1 text-xs font-medium ${changeType === "up" ? "text-emerald-500" : "text-red-500"}`}>
            {changeType === "up" ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            {change}
          </div>
        )}
      </div>
      <div className="text-2xl font-bold text-slate-800">{typeof value === "number" ? value.toLocaleString() : value}</div>
      <div className="text-sm text-text-muted mt-1">{label}</div>
    </div>
  );
}
