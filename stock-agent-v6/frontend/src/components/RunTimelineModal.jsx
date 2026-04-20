/* 弹窗：展示某 run 的完整决策时间线（Recommendations / StockAnalysis 复用）。 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const AGENT_COLOR = {
  supervisor: "var(--agent-supervisor)",
  research:   "var(--agent-research)",
  screener:   "var(--agent-screener)",
  skeptic:    "var(--agent-skeptic)",
  trigger:    "var(--agent-trigger)",
};
const AGENT_ICON  = { supervisor:"🧭", research:"🔬", screener:"⚖️", skeptic:"🔍", trigger:"📡" };
const AGENT_NAME  = { supervisor:"Supervisor", research:"Research", screener:"Screener", skeptic:"Skeptic", trigger:"Trigger" };

export default function RunTimelineModal({ runId, onClose }) {
  const [data, setData] = useState(null);
  const [err,  setErr]  = useState(null);

  useEffect(() => {
    api.getRun(runId).then(setData).catch((e) => setErr(e.message));
  }, [runId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}
        style={{ width: "min(760px, 92vw)", maxHeight: "85vh" }}>
        {/* 头部 */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "var(--gap-md)" }}>
          <h3 style={{ margin: 0 }}>⏱ 执行历史 · Run #{runId}</h3>
          {data && (
            <span className={`badge badge-${data.status}`}>{data.status}</span>
          )}
          {data?.duration_ms && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {(data.duration_ms / 1000).toFixed(1)}s
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button onClick={onClose}
            style={{ background: "transparent", border: "none", cursor: "pointer",
              fontSize: 18, color: "var(--text-muted)", lineHeight: 1 }}>
            ✕
          </button>
        </div>

        <div style={{ overflow: "auto", flex: 1 }}>
          {err && <div style={{ color: "var(--error)" }}>{err}</div>}
          {!data && !err && <div style={{ color: "var(--text-muted)" }}>加载中…</div>}

          {data && (
            <>
              {/* Trigger 摘要 */}
              {data.trigger && (
                <div style={{ padding: "8px 12px", borderRadius: "var(--radius-sm)",
                  background: "rgba(58,107,138,0.06)", marginBottom: "var(--gap-sm)",
                  borderLeft: "3px solid var(--agent-trigger)", fontSize: 12 }}>
                  <span style={{ color: "var(--agent-trigger)", fontWeight: 500 }}>📡 触发事件：</span>
                  <span>{data.trigger.headline}</span>
                </div>
              )}

              {/* 时间线 */}
              {data.timeline.length === 0 ? (
                <div style={{ color: "var(--text-muted)" }}>暂无记录</div>
              ) : (
                <div style={{ position: "relative", paddingLeft: 22 }}>
                  <div style={{ position: "absolute", left: 9, top: 4, bottom: 4,
                    width: 2, background: "var(--border)" }} />
                  {data.timeline.map((node) => (
                    <TimelineNode key={node.id} node={node} />
                  ))}
                </div>
              )}

              {/* Supervisor 综合判断 */}
              {data.supervisor_notes && (
                <div style={{ marginTop: "var(--gap-sm)", padding: "8px 12px",
                  borderLeft: "3px solid var(--agent-supervisor)",
                  borderRadius: "var(--radius-sm)", fontSize: 12, lineHeight: 1.5 }}>
                  <div style={{ color: "var(--agent-supervisor)", fontWeight: 500, marginBottom: 4 }}>
                    🧭 Supervisor 综合判断
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{data.supervisor_notes}</div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function TimelineNode({ node }) {
  const [open, setOpen] = useState(false);
  const color = AGENT_COLOR[node.agent] || "var(--text-muted)";

  return (
    <div style={{ position: "relative", marginBottom: 10, animation: "slideInFromTop 0.2s ease-out" }}>
      <div style={{ position: "absolute", left: -18, top: 8,
        width: 12, height: 12, borderRadius: "50%",
        background: color, border: "2px solid var(--bg)" }} />

      <div onClick={() => setOpen(!open)}
        style={{ border: "1px solid var(--border)", borderLeft: `3px solid ${color}`,
          borderRadius: "var(--radius-sm)", padding: "8px 10px", cursor: "pointer",
          background: "var(--card)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13 }}>{AGENT_ICON[node.agent] || "⚙️"}</span>
          <span style={{ color, fontWeight: 500, fontSize: 12 }}>{AGENT_NAME[node.agent] || node.agent}</span>
          {node.sequence > 0 && (
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>第 {node.sequence} 轮</span>
          )}
          <span className={`badge badge-${node.status === "ok" ? "completed" : node.status === "running" ? "processing" : "failed"}`}
            style={{ fontSize: 10 }}>{node.status}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            {node.created_at ? new Date(node.created_at).toLocaleTimeString("zh-CN", { hour12: false }) : ""}
          </span>
          {node.metrics?.latency_ms && (
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{node.metrics.latency_ms}ms</span>
          )}
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>{open ? "▾" : "▸"}</span>
        </div>
        {node.summary && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3, lineHeight: 1.4 }}>
            {node.summary}
          </div>
        )}

        {open && <NodeDetail node={node} />}
      </div>
    </div>
  );
}

function NodeDetail({ node }) {
  const p = node.payload || {};
  return (
    <div onClick={(e) => e.stopPropagation()}
      style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--border)", fontSize: 11 }}>
      {node.agent === "supervisor" && (
        <>
          {p.action && <Kv k="action" v={<code>{p.action}</code>} />}
          {p.reasoning && <Kv k="reasoning" v={p.reasoning} />}
          {p.instructions && <Kv k="instructions" v={p.instructions} />}
          {p.notes && <Kv k="notes" v={p.notes} />}
        </>
      )}
      {node.agent === "research" && (
        <>
          {p.overall_notes && <Kv k="overall_notes" v={p.overall_notes} />}
          {node.tool_calls?.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: "var(--text-muted)", marginBottom: 3 }}>
                🔧 工具调用 ({node.tool_calls.length})
              </div>
              {node.tool_calls.map((tc) => (
                <div key={tc.sequence} style={{ fontFamily: "DM Mono", fontSize: 10,
                  padding: "2px 6px", marginBottom: 2,
                  borderLeft: `2px solid ${tc.error ? "var(--error)" : "var(--success)"}`,
                  background: "var(--bg)", borderRadius: 3 }}>
                  <span style={{ color: "var(--text-muted)" }}>#{tc.sequence}</span>
                  <span style={{ marginLeft: 6 }}>{tc.tool_name}</span>
                  {tc.stock_code && <span style={{ marginLeft: 6, color: "var(--primary)" }}>({tc.stock_code})</span>}
                  {tc.latency_ms != null && <span style={{ marginLeft: 6, color: "var(--text-muted)" }}>{tc.latency_ms}ms</span>}
                  {tc.error && <span style={{ marginLeft: 6, color: "var(--error)" }}>✗ {tc.error.slice(0, 50)}</span>}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {node.agent === "screener" && (
        <>
          {p.threshold_used != null && <Kv k="threshold_used" v={p.threshold_used} />}
          {p.comparison_summary && <Kv k="comparison_summary" v={p.comparison_summary} />}
        </>
      )}
      {node.agent === "skeptic" && p.covered_stocks?.length > 0 && (
        <Kv k="covered_stocks" v={p.covered_stocks.join(", ")} />
      )}
    </div>
  );
}

function Kv({ k, v }) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 3, lineHeight: 1.5 }}>
      <span style={{ color: "var(--text-muted)", minWidth: 80, flexShrink: 0, fontFamily: "DM Mono", fontSize: 10 }}>{k}</span>
      <span style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v}</span>
    </div>
  );
}
