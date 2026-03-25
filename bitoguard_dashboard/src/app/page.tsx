"use client";
import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { DashboardPage } from "@/components/pages/DashboardPage";
import { QueryPage } from "@/components/pages/QueryPage";
import { GraphPage } from "@/components/pages/GraphPage";
import { ModelPage } from "@/components/pages/ModelPage";

export default function App() {
  const [activePage, setActivePage] = useState("dashboard");
  const [queryId, setQueryId] = useState("");

  const handleSetActive = (page: string) => {
    setActivePage(page);
    if (page !== "query") setQueryId("");
  };

  return (
    <div className="flex min-h-screen" style={{ background: "#F7F9FC" }}>
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
