"use client";

const titles: Record<string, string> = {
  dashboard: "風險總覽 Dashboard",
  query: "用戶風險查詢",
  graph: "交易圖譜視覺化",
  model: "模型解釋性分析",
};

export function TopBar({ page }: { page: string }) {
  return (
    <div className="h-16 bg-white border-b border-slate-100 flex items-center px-8 sticky top-0 z-40">
      <h1 className="text-lg font-semibold text-slate-700">{titles[page] ?? ""}</h1>
    </div>
  );
}
