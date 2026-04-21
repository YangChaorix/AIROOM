/* 触发队列 Tab：Pending / Processing / 已完成触发（按日期筛选）。 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import DatePicker, { toDateKey } from "../../components/DatePicker";

const TYPE_LABEL = {
  policy_landing: "政策落地",
  industry_news: "行业新闻",
  earnings_beat: "业绩异动",
  minor_news: "一般动态",
  price_surge: "价格异动",
  individual_stock_analysis: "个股分析",
  unknown: "未分类",
};

export default function QueueTab({ onToast }) {
  const [data, setData] = useState(null);
  const [completed, setCompleted] = useState([]);
  const [skipped, setSkipped] = useState([]);
  const [consuming, setConsuming] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [date, setDate] = useState(toDateKey(new Date()));

  async function handleRunTrigger() {
    setTriggering(true);
    try {
      await api.runTriggerNow();
      onToast?.("已启动 Trigger Agent（扫描未消费新闻生成触发）");
      setTimeout(refresh, 4000);
      setTimeout(refresh, 10000);
    } catch (e) {
      onToast?.(`触发失败：${e.message}`);
    } finally {
      setTimeout(() => setTriggering(false), 5000);
    }
  }

  async function refresh() {
    try { setData(await api.getQueue()); } catch {}
    try { setCompleted(await api.listTriggers("completed", 50, date)); } catch {}
    try { setSkipped(await api.listTriggers("skipped_duplicate", 50, date)); } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [date]);

  async function handleConsume() {
    setConsuming(true);
    try {
      await api.consume(1);
      onToast?.("已下发消费下一个");
      setTimeout(refresh, 1500);
    } catch (e) { onToast?.(`消费失败：${e.message}`); }
    finally { setTimeout(() => setConsuming(false), 1000); }
  }

  if (!data) return <div className="card">加载中…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>🎯 触发队列</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "var(--agent-trigger)" }}>🔴 Pending {data.counts.pending || 0}</span>
            <span style={{ fontSize: 12, color: "var(--warning)" }}>🟡 Processing {data.counts.processing || 0}</span>
            <span style={{ fontSize: 12, color: "var(--success)" }}>✓ Completed {data.counts.completed || 0}</span>
            {(data.counts.skipped_duplicate || 0) > 0 && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>⎘ Skipped {data.counts.skipped_duplicate}</span>}
            {(data.counts.failed || 0) > 0 && <span style={{ fontSize: 12, color: "var(--error)" }}>✗ Failed {data.counts.failed}</span>}
            <button className="btn" onClick={handleRunTrigger} disabled={triggering}
              style={{ fontSize: 12, padding: "5px 12px", marginLeft: 8 }}>
              {triggering ? "运行中…" : "🎯 立即运行触发"}
            </button>
          </div>
        </div>
      </div>

      {/* Processing */}
      {data.processing && data.processing.length > 0 && (
        <Section title="🟡 Processing" color="var(--warning)">
          {data.processing.map((t) => <TriggerCard key={t.id} t={t} variant="processing" />)}
        </Section>
      )}

      {/* Pending */}
      <Section
        title={`🔴 Pending · ${data.pending?.length || 0}`}
        color="var(--agent-trigger)"
        action={(data.pending || []).length > 0 ? (
          <button className="btn" disabled={consuming} onClick={handleConsume} style={{ fontSize: 12, padding: "5px 10px" }}>
            {consuming ? "已下发…" : "▶ 消费最高优先级"}
          </button>
        ) : null}
      >
        {(data.pending || []).length === 0 ? (
          <EmptyHint text="队列清空了 · Trigger Agent 下次运行会扫描新 news ☕" />
        ) : (
          data.pending.map((t) => <TriggerCard key={t.id} t={t} variant="pending" />)
        )}
      </Section>

      {/* Completed — 带日期筛选 */}
      <Section
        title="✓ 已完成触发"
        color="var(--success)"
        header={<DatePicker value={date} onChange={setDate} />}
      >
        {completed.length === 0 ? (
          <EmptyHint text="该日期暂无已完成触发" />
        ) : (
          completed.map((t) => <TriggerCard key={t.id} t={t} variant="completed" />)
        )}
      </Section>

      {/* Skipped Duplicate — 消费时发现同主题 twin 被合并的 */}
      {skipped.length > 0 && (
        <Section
          title={`⎘ 跳过（主题重复）· ${skipped.length}`}
          color="var(--text-muted)"
        >
          {skipped.map((t) => <TriggerCard key={t.id} t={t} variant="skipped" />)}
        </Section>
      )}
    </div>
  );
}

function Section({ title, color, action, header, children }) {
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: header ? 8 : 10 }}>
        <h4 style={{ margin: 0, color }}>{title}</h4>
        {action}
      </div>
      {header && <div style={{ marginBottom: 10 }}>{header}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {children}
      </div>
    </div>
  );
}

function EmptyHint({ text }) {
  return (
    <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 20 }}>
      {text}
    </div>
  );
}

function fmtHHMM(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false }).slice(0, 5);
  } catch { return ""; }
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  } catch { return ""; }
}

function TriggerCard({ t, variant }) {
  const isHighPri = (t.priority || 5) >= 8;
  const dupCount = t.duplicate_count || 1;
  const isDup = dupCount > 1;
  const [expanded, setExpanded] = useState(false);
  const [news, setNews] = useState(null);  // null=未加载 / []=空 / [...]=已加载
  const [loadingNews, setLoadingNews] = useState(false);
  const newsCount = t.source_news_ids?.length || 0;

  async function toggleNews() {
    const next = !expanded;
    setExpanded(next);
    if (next && news === null && newsCount > 0) {
      setLoadingNews(true);
      try {
        const rows = await api.listNewsByIds(t.source_news_ids);
        // 按 source_news_ids 顺序排序（API 返回按 created_at desc）
        const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
        setNews(t.source_news_ids.map((id) => byId[id]).filter(Boolean));
      } catch (e) {
        setNews([]);
      } finally {
        setLoadingNews(false);
      }
    }
  }
  const color = variant === "processing" ? "var(--warning)" :
    variant === "pending" ? "var(--agent-trigger)" :
    variant === "failed" ? "var(--error)" :
    variant === "skipped" ? "var(--text-muted)" : "var(--success)";

  const style = {
    padding: isHighPri ? 14 : 10,
    border: "1px solid var(--border)",
    borderLeft: `${isHighPri ? 4 : 2}px solid ${color}`,
    borderRadius: "var(--radius-sm)",
    background: "var(--card)",
    boxShadow: isHighPri ? "0 2px 8px rgba(176,125,42,0.10)" : "none",
    animation: variant === "pending" ? "floatSoft 3s ease-in-out infinite" : "none",
    opacity: variant === "skipped" ? 0.75 : 1,
  };

  const theme = t.theme_stats;
  const sameDay = theme && fmtDate(theme.theme_first_seen) === fmtDate(theme.theme_last_seen);

  return (
    <div style={style}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "DM Mono" }}>#{t.id}</span>
        {variant === "pending" && (
          <span style={{ fontSize: 11, fontWeight: 500, color }}>
            🔥 priority {t.priority}
          </span>
        )}
        <span className={`badge badge-${variant === "processing" ? "processing" : variant === "pending" ? "pending" : variant === "failed" ? "failed" : variant === "skipped" ? "completed" : "completed"}`}>
          {variant === "skipped" ? "⎘ skipped" : variant}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {TYPE_LABEL[t.type] || t.type} · {t.strength}
        </span>
        {isDup && (
          <span style={{
            fontSize: 11, fontWeight: 600,
            color: "var(--warning)",
            padding: "1px 7px",
            border: "1px solid var(--warning)",
            borderRadius: 10,
          }} title={`新 news 命中 ${dupCount} 次`}>
            ×{dupCount}
          </span>
        )}
      </div>
      <div style={{ fontSize: isHighPri ? 15 : 13, fontWeight: isHighPri ? 500 : 400, lineHeight: 1.4 }}>
        {t.headline}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        {t.industry} · 来源 {t.source} ·{" "}
        {newsCount > 0 ? (
          <span
            onClick={toggleNews}
            style={{
              color: "var(--primary)", cursor: "pointer",
              textDecoration: "underline", textDecorationStyle: "dotted",
            }}
            title="点击查看原始新闻"
          >
            引用 {newsCount} 条新闻 {expanded ? "▲" : "▼"}
          </span>
        ) : (
          <span>引用 0 条新闻</span>
        )}
      </div>
      {expanded && (
        <div style={{
          marginTop: 8,
          padding: 8,
          background: "rgba(0,0,0,0.02)",
          borderRadius: "var(--radius-sm)",
          border: "1px dashed var(--border)",
        }}>
          {loadingNews ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>加载新闻中…</div>
          ) : !news || news.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>无原始新闻（已被删除？）</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {news.map((n) => <InlineNewsItem key={n.id} n={n} />)}
            </div>
          )}
        </div>
      )}
      {isDup && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          ▼ 首次 {fmtHHMM(t.created_at)} → 最新 {fmtHHMM(t.last_seen_at)}
        </div>
      )}
      {theme && (theme.theme_trigger_rows > 1 || theme.theme_total_hits > 1) && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, opacity: 0.85 }}>
          📊 本主题共 {theme.theme_trigger_rows} 行 / 累计命中 {theme.theme_total_hits} 次
          {!sameDay && ` · ${fmtDate(theme.theme_first_seen)}—${fmtDate(theme.theme_last_seen)}`}
        </div>
      )}
      {t.consumed_by_run_id && (
        <div style={{ marginTop: 6, fontSize: 12 }}>
          {variant === "skipped" ? "⎘ 被吸收至 " : "→ "}
          <Link to={`/runs/${t.consumed_by_run_id}`}>run #{t.consumed_by_run_id}</Link>
        </div>
      )}
    </div>
  );
}

function InlineNewsItem({ n }) {
  const [showFull, setShowFull] = useState(false);
  const time = n.published_at
    ? new Date(n.published_at).toLocaleString("zh-CN", { hour12: false }).slice(5, 16)
    : "";
  const content = n.content || "";
  const hasMore = content.length > 200;
  const preview = hasMore && !showFull ? content.slice(0, 200) + "…" : content;

  return (
    <div style={{
      padding: 8,
      background: "var(--card)",
      borderRadius: 4,
      borderLeft: "2px solid var(--border)",
    }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "DM Mono" }}>#{n.id}</span>
        <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "rgba(0,0,0,0.05)" }}>
          {n.source}
        </span>
        {time && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{time}</span>}
      </div>
      <div style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.4, marginBottom: content ? 4 : 0 }}>
        {n.title}
      </div>
      {content && (
        <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.5, opacity: 0.85, whiteSpace: "pre-wrap" }}>
          {preview}
          {hasMore && (
            <span
              onClick={() => setShowFull(!showFull)}
              style={{ color: "var(--primary)", cursor: "pointer", marginLeft: 6 }}
            >
              {showFull ? "收起" : "展开全文"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
