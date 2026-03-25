export function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: "default" | "danger" | "warning" | "success" | "info" }) {
  const styles: Record<string, string> = {
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
}
