"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import * as d3 from "d3";
import { Network, Search, AlertTriangle, Filter, ExternalLink, ChevronDown, ChevronUp } from "lucide-react";
import { api, type GraphNode as ApiNode, type GraphEdge as ApiEdge, type Alert } from "@/lib/api";
import { C, HEX } from "@/components/ui/constants";

// ─── Bipartite → User-to-User (star topology) ───

interface UserNode { id: string; label: string; risk: number; type: "focus" | "blacklist" | "flagged" | "normal"; }
interface UserEdge { source: string; target: string; relations: string[]; }

function bipartiteToUserGraph(nodes: ApiNode[], edges: ApiEdge[], focusUserId: string) {
  const userNodes = nodes.filter((n) => n.type === "user");
  const entityNodes = new Set(nodes.filter((n) => n.type !== "user").map((n) => n.id));
  const entityTypes: Record<string, string> = {};
  for (const n of nodes) { if (n.type !== "user") entityTypes[n.id] = n.type; }

  const entityToUsers: Record<string, Set<string>> = {};
  for (const e of edges) {
    const isSourceEntity = entityNodes.has(e.source);
    const isTargetEntity = entityNodes.has(e.target);
    const entityId = isSourceEntity ? e.source : isTargetEntity ? e.target : null;
    const userId = isSourceEntity ? e.target : isTargetEntity ? e.source : null;
    if (entityId && userId) {
      if (!entityToUsers[entityId]) entityToUsers[entityId] = new Set();
      entityToUsers[entityId].add(userId);
    }
  }

  const focusNodeId = `user:${focusUserId}`;
  const focusEntities = new Set<string>();
  for (const [entityId, users] of Object.entries(entityToUsers)) {
    if (users.has(focusNodeId)) focusEntities.add(entityId);
  }

  const neighborRelations: Record<string, Set<string>> = {};
  for (const entityId of focusEntities) {
    const eType = entityTypes[entityId];
    const label = eType === "ip" ? "共享 IP" : eType === "wallet" ? "共享錢包" : "關聯";
    for (const uid of entityToUsers[entityId]) {
      if (uid === focusNodeId) continue;
      if (!neighborRelations[uid]) neighborRelations[uid] = new Set();
      neighborRelations[uid].add(label);
    }
  }

  const allNodes: UserNode[] = userNodes.map((n) => ({
    id: n.id, label: n.id.replace("user:", ""),
    risk: n.is_known_blacklist ? 100 : n.risk_level === "critical" ? 95 : n.risk_level === "high" ? 80 : n.risk_level === "medium" ? 50 : 20,
    type: n.id === focusNodeId ? "focus" : n.is_known_blacklist ? "blacklist" : (n.risk_level === "critical" || n.risk_level === "high") ? "flagged" : "normal",
  }));

  const MAX_NEIGHBORS = 15;
  const neighborNodes = allNodes.filter((n) => n.id in neighborRelations || neighborRelations[n.id] !== undefined)
    .filter((n) => Object.keys(neighborRelations).includes(n.id))
    .sort((a, b) => b.risk - a.risk).slice(0, MAX_NEIGHBORS);
  const focusNode = allNodes.find((n) => n.id === focusNodeId);
  const resultNodes = focusNode ? [focusNode, ...neighborNodes] : neighborNodes;
  const keepIds = new Set(resultNodes.map((n) => n.id));
  const resultEdges: UserEdge[] = Object.entries(neighborRelations)
    .filter(([uid]) => keepIds.has(uid))
    .map(([uid, relations]) => ({ source: focusNodeId, target: uid, relations: Array.from(relations) }));

  return { nodes: resultNodes, edges: resultEdges };
}

// ─── D3 types ───
interface D3Node extends d3.SimulationNodeDatum { id: string; label: string; risk: number; type: string; }
interface D3Link extends d3.SimulationLinkDatum<D3Node> { source: string | D3Node; target: string | D3Node; relations: string[]; }

// ─── Alert Item Component ───
function AlertItem({ alert, isSelected, onClick }: { alert: Alert; isSelected: boolean; onClick: () => void }) {
  const score = Math.round(alert.risk_score ?? 0);
  const levelColor = alert.risk_level === "critical" ? HEX.danger : alert.risk_level === "high" ? HEX.warning : "#FFE066";
  return (
    <button onClick={onClick}
      className={`w-full text-left p-3 rounded-lg transition-all ${isSelected ? "bg-blue-50 border-l-4 border-blue-500" : "hover:bg-slate-50 border-l-4 border-transparent"}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-700">{alert.user_id}</span>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: levelColor }} />
          <span className="text-sm font-bold" style={{ color: levelColor }}>{score}</span>
        </div>
      </div>
      <div className="text-xs text-text-muted mt-0.5">{alert.risk_level}</div>
    </button>
  );
}

// ─── Main Component ───
export function GraphPage() {
  const svgRef = useRef<SVGSVGElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const [userId, setUserId] = useState("");
  const [searchVal, setSearchVal] = useState("");
  const [selectedNode, setSelectedNode] = useState<D3Node | null>(null);
  const [filters, setFilters] = useState({ critical: true, high: true, medium: false });
  const [showFilters, setShowFilters] = useState(false);

  // Fetch all alerts for the queue
  const { data: allAlerts } = useQuery({
    queryKey: ["graphAlerts"],
    queryFn: () => api.getAlerts({ page_size: 200 }),
    staleTime: 5 * 60 * 1000,
  });

  const filteredAlerts = (allAlerts?.items ?? []).filter((a) => {
    if (a.risk_level === "critical" && filters.critical) return true;
    if (a.risk_level === "high" && filters.high) return true;
    if (a.risk_level === "medium" && filters.medium) return true;
    return false;
  });

  const levelCounts = {
    critical: (allAlerts?.items ?? []).filter((a) => a.risk_level === "critical").length,
    high: (allAlerts?.items ?? []).filter((a) => a.risk_level === "high").length,
    medium: (allAlerts?.items ?? []).filter((a) => a.risk_level === "medium").length,
  };

  const { data: graphData, isLoading } = useQuery({
    queryKey: ["graph", userId],
    queryFn: () => api.getUserGraph(userId, 2),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });

  const handleSelectUser = useCallback((id: string) => {
    setUserId(id);
    setSearchVal(id);
    setSelectedNode(null);
  }, []);

  // Graph transform
  const userGraphRef = useRef<{ nodes: UserNode[]; edges: UserEdge[] } | null>(null);
  const prevGraphDataRef = useRef(graphData);
  if (graphData !== prevGraphDataRef.current) {
    prevGraphDataRef.current = graphData;
    userGraphRef.current = graphData ? bipartiteToUserGraph(graphData.nodes, graphData.edges, userId) : null;
  }
  const userGraph = userGraphRef.current;

  // D3 rendering
  useEffect(() => {
    if (!svgRef.current || !userGraph || userGraph.nodes.length === 0) return;

    const container = svgRef.current.parentElement!;
    const width = container.clientWidth;
    const height = container.clientHeight || 500;
    const svg = d3.select(svgRef.current).attr("width", width).attr("height", height).attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    const nodes: D3Node[] = userGraph.nodes.map((n) => ({ ...n }));
    const links: D3Link[] = userGraph.edges.map((e) => ({ ...e }));
    if (nodes.length === 0) return;

    const getColor = (d: D3Node) =>
      d.type === "focus" ? HEX.primary : d.type === "blacklist" ? HEX.danger : d.type === "flagged" ? HEX.warning : HEX.safe;
    const getRadius = (d: D3Node) =>
      d.type === "focus" ? 22 : d.type === "blacklist" ? 16 : d.type === "flagged" ? 14 : 10;

    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d: any) => d.id).distance(160))
      .force("charge", d3.forceManyBody().strength(-600))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(45));

    const linkGroup = svg.append("g");
    const link = linkGroup.selectAll("line").data(links).join("line")
      .attr("stroke", "#CBD5E1").attr("stroke-width", 2).attr("opacity", 0.5);

    const edgeLabelGroup = svg.append("g");
    const edgeLabel = edgeLabelGroup.selectAll("text").data(links).join("text")
      .text((d) => (d as any).relations.join(" + "))
      .attr("font-size", 8).attr("fill", "#94A3B8").attr("text-anchor", "middle").attr("pointer-events", "none");

    const nodeGroup = svg.append("g");
    const node = nodeGroup.selectAll("circle").data(nodes).join("circle")
      .attr("r", getRadius).attr("fill", getColor).attr("stroke", "white").attr("stroke-width", 2.5)
      .attr("cursor", "pointer").attr("filter", "drop-shadow(0 2px 4px rgba(0,0,0,0.1))")
      .on("mouseover", function (_: any, d: D3Node) {
        d3.select(this).transition().duration(150).attr("r", getRadius(d) + 4).attr("stroke-width", 3.5);
      })
      .on("mouseout", function (_: any, d: D3Node) {
        d3.select(this).transition().duration(150).attr("r", getRadius(d)).attr("stroke-width", 2.5);
      })
      .on("click", (_: any, d: D3Node) => {
        setSelectedNode(d);
      })
      .call(d3.drag<SVGCircleElement, D3Node>()
        .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    const labelGroup = svg.append("g");
    labelGroup.selectAll("text").data(nodes).join("text")
      .text((d) => d.label)
      .attr("font-size", 10).attr("fill", "#475569").attr("text-anchor", "middle")
      .attr("font-weight", (d) => d.type === "focus" ? "bold" : "normal")
      .attr("dy", (d) => getRadius(d) + 15).attr("pointer-events", "none");

    simulation.on("tick", () => {
      link.attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      edgeLabel.attr("x", (d: any) => (d.source.x + d.target.x) / 2).attr("y", (d: any) => (d.source.y + d.target.y) / 2 - 6);
      node.attr("cx", (d) => d.x!).attr("cy", (d) => d.y!);
      labelGroup.selectAll("text").attr("x", (d: any) => d.x).attr("y", (d: any) => d.y);
    });

    return () => { simulation.stop(); };
  }, [graphData]);

  const typeLabel = (t: string) => t === "focus" ? "查詢用戶" : t === "blacklist" ? "黑名單" : t === "flagged" ? "高風險" : "一般";
  const typeColor = (t: string) => t === "focus" ? HEX.primary : t === "blacklist" ? HEX.danger : t === "flagged" ? HEX.warning : HEX.safe;

  return (
    <div className="flex gap-4 h-[calc(100vh-7rem)]">
      {/* ─── Left Panel: Alert Queue ─── */}
      <div className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-100 flex flex-col overflow-hidden">
        {/* Search */}
        <div className="p-3 border-b border-slate-100">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-300" />
            <input type="text" value={searchVal} onChange={(e) => setSearchVal(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && searchVal.trim()) handleSelectUser(searchVal.trim()); }}
              placeholder="搜尋 User ID..."
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200 transition" />
          </div>
        </div>

        {/* Filters */}
        <div className="px-3 py-2 border-b border-slate-100">
          <button onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 transition w-full">
            <Filter size={12} />
            <span>篩選風險等級</span>
            {showFilters ? <ChevronUp size={12} className="ml-auto" /> : <ChevronDown size={12} className="ml-auto" />}
          </button>
          {showFilters && (
            <div className="flex gap-2 mt-2">
              {([
                { key: "critical" as const, label: "Critical", count: levelCounts.critical, color: HEX.danger },
                { key: "high" as const, label: "High", count: levelCounts.high, color: HEX.warning },
                { key: "medium" as const, label: "Medium", count: levelCounts.medium, color: "#FFE066" },
              ]).map(({ key, label, count, color }) => (
                <button key={key}
                  onClick={() => setFilters((f) => ({ ...f, [key]: !f[key] }))}
                  className={`flex-1 text-center py-1.5 rounded-lg text-xs font-medium border transition ${
                    filters[key] ? "border-slate-300 bg-white shadow-sm" : "border-transparent bg-slate-50 text-text-muted"
                  }`}>
                  <div className="flex items-center justify-center gap-1">
                    <div className="w-2 h-2 rounded-full" style={{ background: filters[key] ? color : "#CBD5E1" }} />
                    {count}
                  </div>
                  <div className="mt-0.5">{label}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Alert List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {filteredAlerts.length === 0 && (
            <div className="text-xs text-text-faint text-center py-8">無符合條件的警報</div>
          )}
          {filteredAlerts.map((a) => (
            <AlertItem key={a.alert_id} alert={a} isSelected={userId === a.user_id}
              onClick={() => handleSelectUser(a.user_id)} />
          ))}
        </div>

        {/* Count */}
        <div className="px-3 py-2 border-t border-slate-100 text-xs text-text-muted text-center">
          共 {filteredAlerts.length} 筆警報
        </div>
      </div>

      {/* ─── Right Panel: Graph + Detail ─── */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
        {/* Graph Area */}
        <div className="flex-1 bg-white rounded-2xl border border-slate-100 flex flex-col overflow-hidden">
          {/* Graph Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-50">
            <div className="flex items-center gap-2">
              <Network size={16} style={{ color: C.primary }} />
              <span className="text-sm font-semibold text-slate-700">
                {userId ? `用戶 ${userId} 的關聯網路` : "交易關聯圖譜"}
              </span>
              {userGraph && (
                <span className="text-xs text-text-muted ml-1">
                  {userGraph.nodes.length} 節點 · {userGraph.edges.length} 邊
                </span>
              )}
            </div>
            <div className="flex gap-3">
              {[
                { c: HEX.primary, l: "查詢用戶" },
                { c: HEX.danger, l: "黑名單" },
                { c: HEX.warning, l: "高風險" },
                { c: HEX.safe, l: "一般" },
              ].map(({ c, l }) => (
                <div key={l} className="flex items-center gap-1 text-xs text-text-muted">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}
                </div>
              ))}
            </div>
          </div>

          {/* SVG */}
          <div className="flex-1 relative bg-slate-50">
            {userId && userGraph && userGraph.nodes.length > 1 ? (
              <svg ref={svgRef} className="w-full h-full" />
            ) : userId && userGraph && userGraph.nodes.length <= 1 ? (
              <div className="flex items-center justify-center h-full text-text-faint text-sm">此用戶無關聯其他用戶</div>
            ) : isLoading ? (
              <div className="flex items-center justify-center h-full text-text-faint text-sm">載入中...</div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-text-faint">
                <Network size={40} className="mb-3 opacity-30" />
                <div className="text-sm">從左側選擇用戶查看關聯圖譜</div>
              </div>
            )}
          </div>
        </div>

        {/* Detail Panel */}
        {selectedNode && (
          <div ref={detailRef} className="bg-white rounded-2xl border border-slate-100 px-5 py-4" style={{ animation: "fadeIn 0.3s ease" }}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `${typeColor(selectedNode.type)}15` }}>
                  <div className="w-4 h-4 rounded-full" style={{ background: typeColor(selectedNode.type) }} />
                </div>
                <div>
                  <div className="text-base font-bold text-slate-800">User {selectedNode.label}</div>
                  <div className="text-xs text-text-muted flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded text-xs font-medium"
                      style={{ background: `${typeColor(selectedNode.type)}15`, color: typeColor(selectedNode.type) }}>
                      {typeLabel(selectedNode.type)}
                    </span>
                    <span>風險分數 {selectedNode.risk}</span>
                    {userGraph && (
                      <span>· {userGraph.edges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id ||
                        (typeof e.source === "object" && (e.source as any).id === selectedNode.id) ||
                        (typeof e.target === "object" && (e.target as any).id === selectedNode.id)
                      ).length} 條關聯</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                {selectedNode.type !== "focus" && (
                  <button onClick={() => handleSelectUser(selectedNode.label)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 hover:bg-slate-50 transition flex items-center gap-1">
                    <Network size={12} /> 展開鄰居
                  </button>
                )}
                <button onClick={() => {
                  const targetId = selectedNode.type === "focus" ? userId : selectedNode.label;
                  window.open(`/?page=query&id=${targetId}`, "_self");
                }}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-white flex items-center gap-1"
                  style={{ background: C.primary }}>
                  <ExternalLink size={12} /> 查看 360°
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
