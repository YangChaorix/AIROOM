import { NavLink } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const NAV = [
  { to: "/", label: "🏠 主页", exact: true },
  { to: "/runs", label: "📋 推荐" },
  { to: "/stock", label: "📊 个股" },
  { to: "/config", label: "⚙️ 配置" },
];

function Counter({ label, count, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "3px 0" }}>
      <span>{label}</span>
      <span style={{ color, fontWeight: 500 }}>{count ?? "-"}</span>
    </div>
  );
}

export default function LeftNav({ onConsume }) {
  const [stats, setStats] = useState(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try { setStats(await api.getInfo()); } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  async function handleConsume() {
    setBusy(true);
    try { await api.consume(1); onConsume?.(); }
    finally { setTimeout(() => setBusy(false), 1500); }
  }

  return (
    <div style={{ width: 160, borderRight: "1px solid var(--border)", padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV.map((it) => (
          <NavLink key={it.to} to={it.to} end={it.exact}
            style={({ isActive }) => ({
              padding: "6px 10px", borderRadius: "var(--radius-sm)",
              background: isActive ? "rgba(176,125,42,0.12)" : "transparent",
              color: isActive ? "var(--primary)" : "var(--text)",
              fontWeight: isActive ? 500 : 400,
            })}
          >{it.label}</NavLink>
        ))}
      </nav>
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>触发队列</div>
        <Counter label="🔴 Pending" count={stats?.queue_pending} color="var(--agent-trigger)" />
        <Counter label="🟡 Process" count={stats?.queue_processing} color="var(--warning)" />
        <Counter label="✓ Runs" count={stats?.runs_total} color="var(--success)" />
        <Counter label="📰 News" count={stats?.news_total} color="var(--text-muted)" />
        <button className="btn" style={{ marginTop: 10, width: "100%", fontSize: 12, padding: "6px 8px" }}
          onClick={handleConsume} disabled={busy || !stats?.queue_pending}>
          {busy ? "已下发…" : "▶ 消费 1 个"}
        </button>
      </div>
    </div>
  );
}
