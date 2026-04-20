/* 概览 Tab：今日数字卡片 + 最近 runs 列表 + SSE 事件流。 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useGlobalStream } from "../../lib/sse";

const AGENT_COLOR = {
  supervisor: "var(--agent-supervisor)",
  research: "var(--agent-research)",
  screener: "var(--agent-screener)",
  skeptic: "var(--agent-skeptic)",
  trigger: "var(--agent-trigger)",
};

export default function OverviewTab() {
  const [info, setInfo] = useState(null);
  const [runs, setRuns] = useState([]);
  const { events, connected } = useGlobalStream();

  async function refresh() {
    try { setInfo(await api.getInfo()); } catch {}
    try { setRuns(await api.listRuns(8)); } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const recent = [...events].reverse().slice(0, 20);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ marginTop: 0, marginBottom: 0 }}>今日概览</h3>
          <span style={{ fontSize: 11, color: connected ? "var(--success)" : "var(--text-muted)" }}>
            {connected ? "● 实时" : "○ 离线"}
          </span>
        </div>
        {info ? (
          <div style={{ display: "flex", gap: "var(--gap-lg)", flexWrap: "wrap", marginTop: 12 }}>
            <Stat label="📰 新闻入库" v={info.news_total} />
            <Stat label="🔴 Pending" v={info.queue_pending} color="var(--agent-trigger)" />
            <Stat label="🟡 Running" v={info.queue_processing} color="var(--warning)" />
            <Stat label="✓ 总 run 数" v={info.runs_total} color="var(--success)" />
          </div>
        ) : <div style={{ color: "var(--text-muted)" }}>加载中…</div>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--gap-md)" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>最近 runs</h3>
          {runs.length === 0 ? (
            <div style={{ color: "var(--text-muted)" }}>暂无运行记录 · Scheduler 会定时生成 trigger</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {runs.map((r) => (
                <Link key={r.id} to={`/runs/${r.id}`}
                  style={{ display: "flex", gap: 12, padding: "6px 8px", borderRadius: "var(--radius-sm)",
                    background: r.status === "running" ? "rgba(200,137,46,0.08)" : "transparent",
                    textDecoration: "none", color: "var(--text)",
                    borderLeft: "3px solid " + (r.status === "completed" ? "var(--success)" : r.status === "failed" ? "var(--error)" : "var(--warning)")
                  }}>
                  <span style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--text-muted)", width: 30 }}>#{r.id}</span>
                  <span className={`badge badge-${r.status}`}>{r.status}</span>
                  <span style={{ flex: 1, fontSize: 13 }}>{r.trigger_key || "—"}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : ""}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="card" style={{ maxHeight: 360, display: "flex", flexDirection: "column" }}>
          <h3 style={{ marginTop: 0 }}>实时事件流</h3>
          <div style={{ overflow: "auto", flex: 1 }}>
            {recent.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
                等待事件…（Scheduler / Agent 触发时会在此滚入）
              </div>
            ) : recent.map((e, i) => (
              <EventRow key={`${e.ts}-${i}`} e={e} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, v, color }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 500, color: color || "var(--text)" }}>
        {v ?? "—"}
      </div>
    </div>
  );
}

function EventRow({ e }) {
  const t = new Date(e.ts).toLocaleTimeString("zh-CN", { hour12: false });
  if (e.type === "agent_output") {
    const color = AGENT_COLOR[e.data.agent] || "var(--text-muted)";
    return (
      <div style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px dashed var(--border)",
        animation: "slideInFromTop 0.3s ease-out" }}>
        <span style={{ color: "var(--text-muted)", marginRight: 6 }}>{t}</span>
        <span style={{ color, fontWeight: 500, marginRight: 6 }}>{e.data.agent}</span>
        <span style={{ color: "var(--text-muted)" }}>run#{e.data.run_id}</span>
        <span style={{ color: "var(--text)", marginLeft: 6 }}>{(e.data.summary || "").slice(0, 50)}</span>
      </div>
    );
  }
  if (e.type === "log") {
    const levelColor = e.data.level === "error" ? "var(--error)" : e.data.level === "warning" ? "var(--warning)" : "var(--text-muted)";
    return (
      <div style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px dashed var(--border)",
        animation: "slideInFromTop 0.3s ease-out" }}>
        <span style={{ color: "var(--text-muted)", marginRight: 6 }}>{t}</span>
        <span style={{ color: levelColor, fontWeight: 500, marginRight: 6 }}>{e.data.level}</span>
        <span style={{ color: "var(--text-muted)", marginRight: 6 }}>{e.data.source}</span>
        <span style={{ color: "var(--text)" }}>{(e.data.message || "").slice(0, 70)}</span>
      </div>
    );
  }
  return null;
}
