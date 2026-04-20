/* 推荐详情：Trigger → 完整时间线（5 个 Agent 气泡卡片） → 推荐股 → 横向对比 → Supervisor 综合判断。
   running 状态下用 SSE 订阅 /api/runs/:id/stream，新节点以 slideInFromTop 动画渐入。 */
import { useEffect, useRef, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";

const AGENT_COLOR = {
  supervisor: "var(--agent-supervisor)",
  research:   "var(--agent-research)",
  screener:   "var(--agent-screener)",
  skeptic:    "var(--agent-skeptic)",
  trigger:    "var(--agent-trigger)",
};
const AGENT_ICON = {
  supervisor: "🧭",
  research:   "🔬",
  screener:   "⚖️",
  skeptic:    "🔍",
  trigger:    "📡",
};
const AGENT_NAME = {
  supervisor: "Supervisor",
  research:   "Research",
  screener:   "Screener",
  skeptic:    "Skeptic",
  trigger:    "Trigger",
};

export default function RunDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [recentRuns, setRecentRuns] = useState([]);
  const esRef = useRef(null);

  // 无 id → 展示最近 run 列表
  useEffect(() => {
    if (id) return;
    api.listRuns(30).then(setRecentRuns).catch((e) => setErr(e.message));
  }, [id]);

  // 有 id → 拉详情 + 若 running 订阅 SSE
  useEffect(() => {
    if (!id) return;
    let alive = true;
    async function load() {
      try {
        const d = await api.getRun(id);
        if (!alive) return;
        setData(d);
        setErr(null);
        if (d.status === "running") subscribe(d);
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    return () => {
      alive = false;
      if (esRef.current) { esRef.current.close(); esRef.current = null; }
    };
    // eslint-disable-next-line
  }, [id]);

  function subscribe(initial) {
    if (esRef.current) return;
    const es = new EventSource(`/api/runs/${id}/stream`);
    esRef.current = es;
    es.addEventListener("agent_output", async () => {
      // 收到新节点 → 重拉完整详情（简单稳妥）
      try { setData(await api.getRun(id)); } catch {}
    });
    es.addEventListener("tool_call", async () => {
      try { setData(await api.getRun(id)); } catch {}
    });
    es.addEventListener("run_end", () => {
      es.close();
      esRef.current = null;
      api.getRun(id).then(setData).catch(() => {});
    });
    es.onerror = () => { /* 断线 → 浏览器自动重连 */ };
  }

  // ── 无 id 视图 ──
  if (!id) {
    return (
      <div style={{ padding: "var(--gap-md)" }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>📋 最近 runs</h3>
          {err && <div style={{ color: "var(--error)" }}>{err}</div>}
          {recentRuns.length === 0 ? (
            <div style={{ color: "var(--text-muted)" }}>暂无运行记录</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {recentRuns.map((r) => (
                <div key={r.id} onClick={() => navigate(`/runs/${r.id}`)}
                  style={{ display: "flex", gap: 12, padding: "8px 10px", cursor: "pointer",
                    borderRadius: "var(--radius-sm)", border: "1px solid var(--border)",
                    borderLeft: "3px solid " + (r.status === "completed" ? "var(--success)" : r.status === "failed" ? "var(--error)" : "var(--warning)") }}>
                  <span style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--text-muted)", width: 40 }}>#{r.id}</span>
                  <span className={`badge badge-${r.status}`}>{r.status}</span>
                  <span style={{ flex: 1, fontSize: 13 }}>{r.trigger_key || "—"}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {r.started_at ? new Date(r.started_at).toLocaleString("zh-CN") : ""}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── 详情视图 ──
  if (err) return <div style={{ padding: "var(--gap-md)" }}><Link to="/runs">← 返回</Link><div className="card" style={{ marginTop: 12, color: "var(--error)" }}>{err}</div></div>;
  if (!data) return <div style={{ padding: "var(--gap-md)" }}><Link to="/runs">← 返回</Link><div className="card" style={{ marginTop: 12 }}>加载中…</div></div>;

  const running = data.status === "running";

  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      {/* 头部 */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Link to="/runs" style={{ fontSize: 13 }}>← 返回</Link>
        <h2 style={{ margin: 0 }}>Run #{data.run_id}</h2>
        <span className={`badge badge-${data.status}`}>{data.status}</span>
        {running && <span style={{ fontSize: 11, color: "var(--warning)" }}>● 实时追踪中</span>}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {data.duration_ms ? `耗时 ${(data.duration_ms / 1000).toFixed(1)}s` : ""}
          {data.trigger_key && ` · ${data.trigger_key}`}
        </span>
      </div>

      {/* Trigger */}
      {data.trigger && <TriggerBanner t={data.trigger} />}

      {/* Timeline */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>🕰️ 决策时间线</h3>
        {data.timeline.length === 0 ? (
          <div style={{ color: "var(--text-muted)" }}>暂无 agent 输出</div>
        ) : (
          <Timeline timeline={data.timeline} running={running} />
        )}
      </div>

      {/* 横向对比 */}
      {data.comparison_summary && (
        <div className="card" style={{ borderLeft: "4px solid var(--agent-screener)" }}>
          <h4 style={{ marginTop: 0, color: "var(--agent-screener)" }}>⚖️ 横向对比摘要</h4>
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>{data.comparison_summary}</div>
        </div>
      )}

      {/* 推荐股 */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>🏆 推荐股（{data.recommendations.length}）</h3>
        {data.recommendations.length === 0 ? (
          <div style={{ color: "var(--text-muted)" }}>本次 run 无推荐</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
            {data.recommendations.map((r) => <RecommendationCard key={r.id} r={r} />)}
          </div>
        )}
      </div>

      {/* Supervisor 综合判断 */}
      {data.supervisor_notes && (
        <div className="card" style={{ borderLeft: "4px solid var(--agent-supervisor)" }}>
          <h4 style={{ marginTop: 0, color: "var(--agent-supervisor)" }}>🧭 Supervisor 综合判断</h4>
          <div style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{data.supervisor_notes}</div>
        </div>
      )}

      {data.error && (
        <div className="card" style={{ borderLeft: "4px solid var(--error)" }}>
          <h4 style={{ marginTop: 0, color: "var(--error)" }}>❌ 失败详情</h4>
          <pre style={{ fontSize: 11, overflow: "auto", maxHeight: 300 }}>{data.error}</pre>
        </div>
      )}

      <details>
        <summary style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: 12 }}>原始 JSON（debug）</summary>
        <pre style={{ maxHeight: 400, overflow: "auto", fontSize: 10, background: "#fff", padding: 12, border: "1px solid var(--border)", marginTop: 8 }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function TriggerBanner({ t }) {
  return (
    <div className="card" style={{ borderLeft: `4px solid var(--agent-trigger)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: "var(--agent-trigger)", fontWeight: 500 }}>📡 TRIGGER</span>
        <span style={{ fontFamily: "DM Mono", fontSize: 11, color: "var(--text-muted)" }}>{t.trigger_id}</span>
        <span className={`badge`} style={{ background: "rgba(58,107,138,0.1)", color: "var(--agent-trigger)" }}>
          {t.strength} · priority {t.priority}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{t.type} · {t.mode}</span>
      </div>
      <div style={{ fontSize: 15, fontWeight: 500, lineHeight: 1.4 }}>{t.headline}</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
        {t.industry} · 来源 {t.source} · 引用 {t.source_news_ids?.length || 0} 条新闻
      </div>
      {t.summary && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.5 }}>{t.summary}</div>
      )}
    </div>
  );
}

function Timeline({ timeline, running }) {
  return (
    <div style={{ position: "relative", paddingLeft: 24 }}>
      {/* 竖线 */}
      <div style={{ position: "absolute", left: 10, top: 0, bottom: 0, width: 2, background: "var(--border)" }} />
      {timeline.map((node, i) => (
        <TimelineNode key={node.id} node={node} isLast={i === timeline.length - 1 && running} />
      ))}
    </div>
  );
}

function TimelineNode({ node, isLast }) {
  const [open, setOpen] = useState(false);
  const color = AGENT_COLOR[node.agent] || "var(--text-muted)";
  const icon = AGENT_ICON[node.agent] || "⚙️";
  const name = AGENT_NAME[node.agent] || node.agent;

  return (
    <div style={{ position: "relative", marginBottom: 14, animation: "slideInFromTop 0.25s ease-out" }}>
      {/* 圆点 */}
      <div style={{
        position: "absolute", left: -20, top: 8,
        width: 14, height: 14, borderRadius: "50%",
        background: color, border: "2px solid var(--bg)",
        animation: isLast ? "breathe 1.6s ease-in-out infinite" : "none",
      }} />

      <div onClick={() => setOpen(!open)} style={{
        background: "var(--card)", border: "1px solid var(--border)",
        borderLeft: `3px solid ${color}`, borderRadius: "var(--radius-sm)",
        padding: 10, cursor: "pointer",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14 }}>{icon}</span>
          <span style={{ color, fontWeight: 500, fontSize: 13 }}>{name}</span>
          {node.sequence > 0 && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>· 第 {node.sequence} 轮</span>}
          <span className={`badge badge-${node.status === "ok" ? "completed" : node.status === "running" ? "processing" : "failed"}`}>
            {node.status}
          </span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {node.created_at ? new Date(node.created_at).toLocaleTimeString("zh-CN", { hour12: false }) : ""}
          </span>
          {node.metrics?.latency_ms && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>· {node.metrics.latency_ms}ms</span>
          )}
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>{open ? "▾" : "▸"}</span>
        </div>
        {node.summary && (
          <div style={{ fontSize: 12, color: "var(--text)", marginTop: 4, lineHeight: 1.5 }}>
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
      style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--border)", fontSize: 12 }}>
      {/* Supervisor：action / reasoning / notes */}
      {node.agent === "supervisor" && (
        <>
          {p.action && <Kv k="action" v={<code>{p.action}</code>} />}
          {p.reasoning && <Kv k="reasoning" v={p.reasoning} />}
          {p.instructions && <Kv k="instructions" v={p.instructions} />}
          {p.notes && <Kv k="notes" v={p.notes} />}
        </>
      )}

      {/* Research：候选股 + 工具调用 */}
      {node.agent === "research" && (
        <>
          {p.overall_notes && <Kv k="overall_notes" v={p.overall_notes} />}
          {p.candidates?.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>候选股 ({p.candidates.length})：</div>
              {p.candidates.map((c, i) => (
                <div key={i} style={{ padding: 6, border: "1px solid var(--border)", borderRadius: 4, marginBottom: 4 }}>
                  <strong>{c.name} · {c.code}</strong> · {c.industry}
                  {c.leadership && <div style={{ color: "var(--text-muted)", fontSize: 11, marginTop: 2 }}>🏭 {c.leadership}</div>}
                  {c.financial_summary && <div style={{ color: "var(--text-muted)", fontSize: 11, marginTop: 2 }}>💰 {c.financial_summary}</div>}
                </div>
              ))}
            </div>
          )}
          {node.tool_calls?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>🔧 工具调用 ({node.tool_calls.length})：</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {node.tool_calls.map((tc) => (
                  <div key={tc.sequence} style={{
                    padding: "4px 8px", fontSize: 11,
                    background: tc.error ? "rgba(180,74,58,0.06)" : "var(--bg)",
                    borderRadius: 4, borderLeft: `2px solid ${tc.error ? "var(--error)" : "var(--success)"}`,
                    fontFamily: "DM Mono",
                  }}>
                    <span style={{ color: "var(--text-muted)" }}>#{tc.sequence}</span>
                    <span style={{ marginLeft: 6, color: tc.error ? "var(--error)" : "var(--text)" }}>{tc.tool_name}</span>
                    {tc.stock_code && <span style={{ marginLeft: 6, color: "var(--primary)" }}>({tc.stock_code})</span>}
                    {tc.latency_ms != null && <span style={{ marginLeft: 6, color: "var(--text-muted)" }}>{tc.latency_ms}ms</span>}
                    {tc.error && <span style={{ marginLeft: 6, color: "var(--error)" }}>✗ {tc.error.slice(0, 60)}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Screener：comparison_summary + threshold */}
      {node.agent === "screener" && (
        <>
          {p.threshold_used != null && <Kv k="threshold_used" v={p.threshold_used} />}
          {p.candidates_count != null && <Kv k="candidates_count" v={p.candidates_count} />}
          {p.comparison_summary && <Kv k="comparison_summary" v={p.comparison_summary} />}
        </>
      )}

      {/* Skeptic：covered_stocks */}
      {node.agent === "skeptic" && (
        <>
          {p.covered_stocks?.length > 0 && (
            <Kv k="covered_stocks" v={p.covered_stocks.join(", ")} />
          )}
          {p.findings_count != null && <Kv k="findings_count" v={p.findings_count} />}
        </>
      )}

      {/* Trigger */}
      {node.agent === "trigger" && (
        <>
          {p.industry && <Kv k="industry" v={p.industry} />}
          {p.strength && <Kv k="strength" v={p.strength} />}
          {p.priority != null && <Kv k="priority" v={p.priority} />}
        </>
      )}

      {/* metrics */}
      {node.metrics && Object.keys(node.metrics).length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: 11 }}>
            metrics ({Object.keys(node.metrics).length})
          </summary>
          <pre style={{ fontSize: 10, background: "var(--bg)", padding: 6, borderRadius: 4, marginTop: 4, overflow: "auto" }}>
            {JSON.stringify(node.metrics, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function Kv({ k, v }) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 4, lineHeight: 1.5 }}>
      <span style={{ color: "var(--text-muted)", minWidth: 90, flexShrink: 0, fontFamily: "DM Mono", fontSize: 11 }}>{k}</span>
      <span style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v}</span>
    </div>
  );
}

function RecommendationCard({ r }) {
  const [open, setOpen] = useState(false);
  const color = r.level === "recommend" ? "var(--success)" : r.level === "watch" ? "var(--warning)" : "var(--text-muted)";
  return (
    <div style={{
      border: "1px solid var(--border)", borderLeft: `4px solid ${color}`,
      borderRadius: "var(--radius-sm)", padding: 12, background: "var(--card)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "DM Mono", width: 28 }}>#{r.rank || "—"}</span>
        <strong style={{ fontSize: 16 }}>{r.name}</strong>
        <span style={{ fontFamily: "DM Mono", color: "var(--text-muted)" }}>{r.code}</span>
        <span className={`badge badge-${r.level}`}>{r.level}</span>
        <span style={{ fontWeight: 500, color }}>{r.total_score.toFixed(2)}</span>
        <span style={{ flex: 1 }} />
        <Link to={`/stock?code=${r.code}`} style={{ fontSize: 12 }}>查看个股 →</Link>
      </div>

      {r.recommendation_rationale && (
        <div style={{ fontSize: 13, color: "var(--text)", marginTop: 8, lineHeight: 1.5 }}>
          💬 {r.recommendation_rationale}
        </div>
      )}

      {(r.key_strengths?.length > 0 || r.key_risks?.length > 0) && (
        <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
          {r.key_strengths?.map((s, i) => (
            <span key={`s${i}`} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
              background: "rgba(91,138,58,0.12)", color: "var(--success)" }}>
              ✓ {s}
            </span>
          ))}
          {r.key_risks?.map((s, i) => (
            <span key={`r${i}`} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
              background: "rgba(180,74,58,0.10)", color: "var(--error)" }}>
              ⚠ {s}
            </span>
          ))}
        </div>
      )}

      <button onClick={() => setOpen(!open)}
        style={{ marginTop: 8, fontSize: 11, background: "transparent", border: "1px solid var(--border)",
          color: "var(--text-muted)", padding: "3px 10px", borderRadius: 12, cursor: "pointer" }}>
        {open ? "▾ 收起打分 & 质疑" : "▸ 展开打分 & 质疑"}
      </button>

      {open && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--border)" }}>
          {/* 打分 */}
          {r.condition_scores?.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>⚖️ 条件打分</div>
              <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ color: "var(--text-muted)", fontSize: 11, textAlign: "left" }}>
                    <th style={{ padding: "4px 6px" }}>条件</th>
                    <th style={{ padding: "4px 6px", width: 50 }}>满足</th>
                    <th style={{ padding: "4px 6px", width: 50 }}>权重</th>
                    <th style={{ padding: "4px 6px", width: 60 }}>加权</th>
                    <th style={{ padding: "4px 6px" }}>理由</th>
                  </tr>
                </thead>
                <tbody>
                  {r.condition_scores.map((s) => (
                    <tr key={s.condition_id} style={{ borderTop: "1px dashed var(--border)" }}>
                      <td style={{ padding: "4px 6px" }}><code>{s.condition_id}</code> {s.condition_name}</td>
                      <td style={{ padding: "4px 6px", color: s.satisfaction >= 1 ? "var(--success)" : s.satisfaction >= 0.5 ? "var(--warning)" : "var(--error)" }}>
                        {s.satisfaction}
                      </td>
                      <td style={{ padding: "4px 6px", color: "var(--text-muted)" }}>{s.weight}</td>
                      <td style={{ padding: "4px 6px", fontWeight: 500 }}>{s.weighted_score.toFixed(3)}</td>
                      <td style={{ padding: "4px 6px", color: "var(--text-muted)", lineHeight: 1.4 }}>{s.reasoning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 质疑 */}
          {r.skeptic_findings?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "var(--agent-skeptic)", marginBottom: 6 }}>🔍 Skeptic 质疑 ({r.skeptic_findings.length})</div>
              {r.skeptic_findings.map((f, i) => (
                <div key={i} style={{ padding: 6, marginBottom: 4, borderLeft: "3px solid var(--agent-skeptic)",
                  borderRadius: 4, background: "rgba(180,74,58,0.04)" }}>
                  <span style={{ fontSize: 10, color: "var(--agent-skeptic)", fontWeight: 500 }}>
                    {f.finding_type === "logic_risk" ? "⚠ 逻辑风险" : "📊 数据缺口"}
                  </span>
                  <div style={{ fontSize: 12, marginTop: 2, lineHeight: 1.5 }}>{f.content}</div>
                </div>
              ))}
            </div>
          )}

          {/* 数据缺口 */}
          {r.data_gaps?.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)" }}>
              数据缺口：{r.data_gaps.join("、")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
