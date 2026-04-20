import { NavLink } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const NAV_TOP = [
  { to: "/",      label: "🏆 推荐",    exact: true },
  { to: "/news",  label: "📰 新闻" },
  { to: "/stock", label: "📊 个股分析" },
  { to: "/config",label: "⚙️ 配置" },
];
const NAV_BOTTOM = [
  { to: "/runs",  label: "📋 执行历史" },
];

function Counter({ label, count, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "3px 0" }}>
      <span>{label}</span>
      <span style={{ color, fontWeight: 500 }}>{count ?? "-"}</span>
    </div>
  );
}

export default function LeftNav() {
  const [stats, setStats] = useState(null);

  async function refresh() {
    try { setStats(await api.getInfo()); } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ width: 160, borderRight: "1px solid var(--border)", padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NAV_TOP.map((it) => (
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
      <div style={{ flex: 1 }} />
      <nav style={{ display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
        {NAV_BOTTOM.map((it) => (
          <NavLink key={it.to} to={it.to}
            style={({ isActive }) => ({
              padding: "6px 10px", borderRadius: "var(--radius-sm)",
              background: isActive ? "rgba(176,125,42,0.12)" : "transparent",
              color: isActive ? "var(--primary)" : "var(--text-muted)",
              fontWeight: isActive ? 500 : 400, fontSize: 13,
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
      </div>
    </div>
  );
}
