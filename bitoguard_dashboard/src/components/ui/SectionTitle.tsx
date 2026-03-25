import type { LucideIcon } from "lucide-react";
import { C } from "./constants";

export function SectionTitle({ icon: Icon, title, subtitle }: { icon: LucideIcon; title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2.5 mb-1">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${C.gradientA}, ${C.gradientB})` }}>
          <Icon size={16} color="white" />
        </div>
        <h2 className="text-xl font-bold text-slate-800">{title}</h2>
      </div>
      {subtitle && <p className="text-sm text-text-muted ml-10">{subtitle}</p>}
    </div>
  );
}
