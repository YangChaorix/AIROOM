/* 日志 Tab：按 level/source 过滤的 system_logs 流。 */
import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function LogsTab() {
  const [logs, setLogs] = useState([]);
  const [level, setLevel] = useState("all");
  const [sourcePrefix, setSourcePrefix] = useState("");

  async function refresh() {
    try {
      setLogs(await api.listLogs({
        level: level === "all" ? undefined : level,
        source_prefix: sourcePrefix || undefined,
        limit: 100,
      }));
    } catch {}
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [level, sourcePrefix]);

  return (
    <div className="card" style={{ height: "calc(100vh - 170px)", display: "flex", flexDirection: "column" }}>
      <h3 style={{ marginTop: 0 }}>📜 系统日志</h3>

      <div style={{ display: "flex", gap: 8, marginBottom: "var(--gap-md)", flexWrap: "wrap" }}>
        <Chip active={level === "all"}   onClick={() => setLevel("all")}>all</Chip>
        <Chip active={level === "info"}  onClick={() => setLevel("info")}  color="var(--text-muted)">ⓘ info</Chip>
        <Chip active={level === "warning"} onClick={() => setLevel("warning")} color="var(--warning)">⚠️ warning</Chip>
        <Chip active={level === "error"} onClick={() => setLevel("error")} color="var(--error)">❌ error</Chip>
        <span style={{ borderLeft: "1px solid var(--border)", margin: "0 4px" }} />
        <Chip active={sourcePrefix === ""} onClick={() => setSourcePrefix("")}>all sources</Chip>
        <Chip active={sourcePrefix === "scheduler"} onClick={() => setSourcePrefix("scheduler")}>scheduler.*</Chip>
        <Chip active={sourcePrefix === "agents"} onClick={() => setSourcePrefix("agents")}>agents.*</Chip>
        <Chip active={sourcePrefix === "main"} onClick={() => setSourcePrefix("main")}>main.*</Chip>
      </div>

      <div style={{ overflow: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
        {logs.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 20 }}>
            暂无日志
          </div>
        ) : logs.map((l) => <LogRow key={l.id} log={l} />)}
      </div>
    </div>
  );
}

function Chip({ active, onClick, children, color }) {
  return (
    <button onClick={onClick}
      style={{ padding: "3px 10px", border: "1px solid " + (active ? (color || "var(--primary)") : "var(--border)"),
        background: active ? (color || "var(--primary)") : "transparent",
        color: active ? "white" : "var(--text)", borderRadius: 14, fontSize: 12, cursor: "pointer" }}>
      {children}
    </button>
  );
}

function LogRow({ log }) {
  const levelColor = log.level === "error" ? "var(--error)" : log.level === "warning" ? "var(--warning)" : "var(--text-muted)";
  const levelIcon = log.level === "error" ? "❌" : log.level === "warning" ? "⚠️" : "ⓘ";
  const fontSize = log.level === "error" ? 13 : log.level === "warning" ? 12 : 11;

  let context = null;
  if (log.context) {
    try { context = JSON.parse(log.context); } catch {}
  }

  return (
    <div style={{
      padding: "6px 10px",
      borderLeft: "3px solid " + levelColor,
      background: log.level === "error" ? "rgba(180,74,58,0.04)" : "transparent",
      borderRadius: "var(--radius-sm)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-muted)" }}>
        <span>{levelIcon}</span>
        <span style={{ color: levelColor, fontWeight: 500 }}>{log.level}</span>
        <span>·</span>
        <span>{new Date(log.created_at).toLocaleTimeString("zh-CN", { hour12: false })}</span>
        <span>·</span>
        <span style={{ fontFamily: "DM Mono" }}>{log.source}</span>
        {log.run_id && <><span>·</span><span>run #{log.run_id}</span></>}
      </div>
      <div style={{ fontSize, marginTop: 3, color: "var(--text)" }}>
        {log.message}
      </div>
      {context && (log.level === "error" || Object.keys(context).length > 0) && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer", fontSize: 10, color: "var(--text-muted)" }}>
            上下文 ({Object.keys(context).length} 项)
          </summary>
          <pre style={{ fontSize: 10, background: "var(--bg)", padding: 6, borderRadius: 4, marginTop: 4,
            maxHeight: 200, overflow: "auto" }}>
            {JSON.stringify(context, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
