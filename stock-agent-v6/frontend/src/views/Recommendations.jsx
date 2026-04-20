/* 推荐模块：按 trigger 分组展示推荐股票，右上角弹窗查看决策时间线。 */
import { useEffect, useState, useMemo } from "react";
import { api } from "../lib/api";
import RunTimelineModal from "../components/RunTimelineModal";

const TYPE_LABEL = {
  policy_landing:           "政策落地",
  industry_news:            "行业动态",
  earnings_beat:            "业绩异动",
  minor_news:               "一般动态",
  price_surge:              "价格异动",
  individual_stock_analysis:"个股分析",
  unknown:                  "未分类",
};

const STRENGTH_COLOR = {
  high:   "var(--error)",
  medium: "var(--warning)",
  low:    "var(--text-muted)",
};

function toDateKey(isoStr) {
  if (!isoStr) return "未知";
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dateLabel(key) {
  const today     = toDateKey(new Date().toISOString());
  const yesterday = toDateKey(new Date(Date.now() - 86400000).toISOString());
  if (key === today)     return "今天";
  if (key === yesterday) return "昨天";
  const [, m, d] = key.split("-");
  return `${parseInt(m)}月${parseInt(d)}日`;
}

export default function Recommendations() {
  const [allGroups, setAllGroups] = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [selDate,   setSelDate]   = useState(null); // 选中日期 key
  const [timelineRunId, setTimelineRunId] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.listRecommendations(30)
      .then((data) => {
        setAllGroups(data);
        // 默认选最新一天
        if (data.length > 0) setSelDate(toDateKey(data[0].run_started_at));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // 按日期分组 {dateKey: [group,...]}
  const byDate = useMemo(() => {
    const map = {};
    for (const g of allGroups) {
      const key = toDateKey(g.run_started_at);
      (map[key] ||= []).push(g);
    }
    return map;
  }, [allGroups]);

  const dates       = Object.keys(byDate).sort((a, b) => b.localeCompare(a)); // 最新在前
  const curGroups   = selDate ? (byDate[selDate] || []) : [];
  const totalStocks = curGroups.reduce((s, g) => s + g.stocks.length, 0);

  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      {/* 日期筛选 tab 栏 */}
      <div className="card" style={{ padding: "12px var(--gap-md)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>🏆 推荐股票</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {loading ? "加载中…" : selDate ? `${curGroups.length} 个触发 · ${totalStocks} 只` : ""}
          </span>
          <span style={{ flex: 1 }} />
          {loading
            ? <span style={{ fontSize: 12, color: "var(--text-muted)" }}>加载中…</span>
            : dates.length === 0
              ? <span style={{ fontSize: 12, color: "var(--text-muted)" }}>暂无数据</span>
              : dates.map((key) => (
                  <button key={key} onClick={() => setSelDate(key)}
                    style={{ padding: "4px 12px", fontSize: 12, borderRadius: 14, cursor: "pointer",
                      border: "1px solid " + (selDate === key ? "var(--primary)" : "var(--border)"),
                      background: selDate === key ? "var(--primary)" : "transparent",
                      color: selDate === key ? "white" : "var(--text-muted)",
                      fontWeight: selDate === key ? 500 : 400 }}>
                    {dateLabel(key)}
                    <span style={{ marginLeft: 4, fontSize: 10, opacity: 0.8 }}>
                      {byDate[key].reduce((s, g) => s + g.stocks.length, 0)}只
                    </span>
                  </button>
                ))
          }
        </div>
      </div>

      {!loading && selDate && curGroups.length === 0 && (
        <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--text-muted)" }}>
          {dateLabel(selDate)} 暂无推荐记录
        </div>
      )}

      {curGroups.map((g) => (
        <TriggerGroup key={g.run_id} g={g} onShowTimeline={() => setTimelineRunId(g.run_id)} />
      ))}

      {timelineRunId && (
        <RunTimelineModal runId={timelineRunId} onClose={() => setTimelineRunId(null)} />
      )}
    </div>
  );
}

function TriggerGroup({ g, onShowTimeline }) {
  const t = g.trigger;
  const strengthColor = STRENGTH_COLOR[t.strength] || "var(--text-muted)";
  const runAt = g.run_started_at ? new Date(g.run_started_at) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-sm)" }}>
      {/* Trigger 标题行 */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {t.strength && (
              <span style={{ fontSize: 11, fontWeight: 600, color: strengthColor }}>
                {t.strength === "high" ? "🔥" : t.strength === "medium" ? "⚡" : "·"} {t.strength?.toUpperCase()}
              </span>
            )}
            <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
              background: "rgba(58,107,138,0.1)", color: "var(--agent-trigger)" }}>
              {TYPE_LABEL[t.type] || t.type}
            </span>
            {t.industry && (
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{t.industry}</span>
            )}
            {t.mode === "fixture" && (
              <span style={{ fontSize: 10, color: "var(--text-muted)", border: "1px dashed var(--border)",
                padding: "1px 6px", borderRadius: 8 }}>fixture</span>
            )}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {runAt ? `${runAt.getMonth() + 1}/${runAt.getDate()} ${runAt.getHours().toString().padStart(2,"0")}:${runAt.getMinutes().toString().padStart(2,"0")}` : ""}
              {g.run_duration_ms ? ` · ${(g.run_duration_ms / 1000).toFixed(1)}s` : ""}
            </span>
            <button onClick={onShowTimeline}
              style={{ fontSize: 11, padding: "3px 10px", borderRadius: 12, cursor: "pointer",
                border: "1px solid var(--border)", background: "transparent",
                color: "var(--text-muted)" }}>
              ⏱ 执行历史
            </button>
          </div>
          <div style={{ fontSize: 15, fontWeight: 500, marginTop: 4, lineHeight: 1.4 }}>
            {t.headline}
          </div>
          {t.summary && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.5 }}>
              {t.summary}
            </div>
          )}
        </div>
      </div>

      {/* 推荐股票卡片 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "var(--gap-sm)" }}>
        {g.stocks.map((s) => (
          <StockCard key={s.id} s={s} />
        ))}
      </div>

      <div style={{ borderBottom: "1px dashed var(--border)", marginTop: 4 }} />
    </div>
  );
}

function StockCard({ s }) {
  const [expanded, setExpanded] = useState(false);
  const color = s.level === "recommend" ? "var(--success)" : "var(--warning)";

  return (
    <div style={{
      border: "1px solid var(--border)", borderLeft: `4px solid ${color}`,
      borderRadius: "var(--radius-sm)", padding: 12, background: "var(--card)",
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      {/* 头部：名称/代码/评级/分数 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {s.rank && (
          <span style={{ fontFamily: "DM Mono", fontSize: 11, color: "var(--text-muted)", width: 20 }}>
            #{s.rank}
          </span>
        )}
        <strong style={{ fontSize: 15 }}>{s.name}</strong>
        <span style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--text-muted)" }}>{s.code}</span>
        <span className={`badge badge-${s.level}`}>{s.level === "recommend" ? "推荐" : "观察"}</span>
        <span style={{ marginLeft: "auto", fontWeight: 600, color, fontSize: 14 }}>
          {s.total_score.toFixed(2)}
        </span>
      </div>

      {/* 推荐理由 */}
      {s.recommendation_rationale && (
        <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--text)" }}>
          {s.recommendation_rationale}
        </div>
      )}

      {/* 优势/风险 chip */}
      {(s.key_strengths?.length > 0 || s.key_risks?.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {s.key_strengths?.map((v, i) => (
            <span key={`s${i}`} style={{ fontSize: 10, padding: "2px 7px", borderRadius: 10,
              background: "rgba(91,138,58,0.12)", color: "var(--success)" }}>✓ {v}</span>
          ))}
          {s.key_risks?.map((v, i) => (
            <span key={`r${i}`} style={{ fontSize: 10, padding: "2px 7px", borderRadius: 10,
              background: "rgba(180,74,58,0.10)", color: "var(--error)" }}>⚠ {v}</span>
          ))}
        </div>
      )}

      {/* 展开：打分 + Skeptic */}
      {(s.condition_scores?.length > 0 || s.skeptic_findings?.length > 0) && (
        <>
          <button onClick={() => setExpanded(!expanded)}
            style={{ alignSelf: "flex-start", fontSize: 11, padding: "2px 10px",
              borderRadius: 12, cursor: "pointer", border: "1px solid var(--border)",
              background: "transparent", color: "var(--text-muted)" }}>
            {expanded ? "▾ 收起" : `▸ 打分明细${s.skeptic_findings?.length ? ` · ${s.skeptic_findings.length} 条质疑` : ""}`}
          </button>

          {expanded && (
            <div style={{ borderTop: "1px dashed var(--border)", paddingTop: 8, fontSize: 12 }}>
              {s.condition_scores?.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ color: "var(--text-muted)" }}>
                      <th style={{ textAlign: "left", padding: "3px 4px" }}>条件</th>
                      <th style={{ padding: "3px 4px", width: 40 }}>满足</th>
                      <th style={{ padding: "3px 4px", width: 45 }}>权重</th>
                      <th style={{ padding: "3px 4px", width: 50 }}>加权</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.condition_scores.map((sc) => (
                      <tr key={sc.condition_id} style={{ borderTop: "1px dashed var(--border)" }}>
                        <td style={{ padding: "3px 4px" }}><code>{sc.condition_id}</code> {sc.condition_name}</td>
                        <td style={{ padding: "3px 4px", textAlign: "center",
                          color: sc.satisfaction >= 1 ? "var(--success)" : sc.satisfaction >= 0.5 ? "var(--warning)" : "var(--error)" }}>
                          {sc.satisfaction}
                        </td>
                        <td style={{ padding: "3px 4px", textAlign: "center", color: "var(--text-muted)" }}>{sc.weight}</td>
                        <td style={{ padding: "3px 4px", textAlign: "center", fontWeight: 500 }}>{sc.weighted_score?.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {s.skeptic_findings?.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 11, color: "var(--agent-skeptic)", fontWeight: 500, marginBottom: 4 }}>
                    🔍 Skeptic 质疑
                  </div>
                  {s.skeptic_findings.map((f, i) => (
                    <div key={i} style={{ padding: "4px 8px", marginBottom: 3,
                      borderLeft: "2px solid var(--agent-skeptic)", fontSize: 11,
                      background: "rgba(180,74,58,0.04)", borderRadius: 3 }}>
                      <span style={{ color: "var(--agent-skeptic)", fontSize: 10 }}>
                        {f.finding_type === "logic_risk" ? "⚠ 逻辑风险" : "📊 数据缺口"}
                      </span>
                      <div style={{ marginTop: 2 }}>{f.content}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
