/* 新闻中心：新闻流 / 触发队列 / 日志 三个 Tab。 */
import { useState } from "react";
import NewsTab   from "./home/NewsTab";
import QueueTab  from "./home/QueueTab";
import LogsTab   from "./home/LogsTab";

const TABS = [
  { id: "news",  label: "📰 新闻流" },
  { id: "queue", label: "🎯 触发队列" },
  { id: "logs",  label: "📜 日志" },
];

export default function NewsCenter({ onToast }) {
  const [tab, setTab] = useState("news");
  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)", height: "100%" }}>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)" }}>
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            style={{ padding: "8px 16px", border: "none", background: "transparent",
              color: tab === t.id ? "var(--primary)" : "var(--text-muted)",
              fontWeight: tab === t.id ? 500 : 400,
              borderBottom: "2px solid " + (tab === t.id ? "var(--primary)" : "transparent"),
              cursor: "pointer", fontSize: 14, marginBottom: -1 }}>
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        {tab === "news"  && <NewsTab onToast={onToast} />}
        {tab === "queue" && <QueueTab onToast={onToast} />}
        {tab === "logs"  && <LogsTab />}
      </div>
    </div>
  );
}
