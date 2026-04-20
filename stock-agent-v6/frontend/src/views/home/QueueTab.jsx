/* 触发队列 Tab：事件卡片堆 —— pending 悬浮漂浮、processing 旋转光环、failed 红边。 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";

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
  const [consuming, setConsuming] = useState(false);

  async function refresh() {
    try { setData(await api.getQueue()); } catch {}
    try { setCompleted(await api.listTriggers("completed", 10)); } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

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
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>🎯 触发队列</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--agent-trigger)" }}>🔴 Pending {data.counts.pending || 0}</span>
            <span style={{ fontSize: 12, color: "var(--warning)" }}>🟡 Processing {data.counts.processing || 0}</span>
            <span style={{ fontSize: 12, color: "var(--success)" }}>✓ Completed {data.counts.completed || 0}</span>
            {(data.counts.failed || 0) > 0 && <span style={{ fontSize: 12, color: "var(--error)" }}>✗ Failed {data.counts.failed}</span>}
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

      {/* Recent completed */}
      <Section title="✓ 最近 completed" color="var(--success)">
        {completed.length === 0 ? (
          <EmptyHint text="暂无已完成 trigger" />
        ) : (
          completed.map((t) => <TriggerCard key={t.id} t={t} variant="completed" />)
        )}
      </Section>
    </div>
  );
}

function Section({ title, color, action, children }) {
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <h4 style={{ margin: 0, color }}>{title}</h4>
        {action}
      </div>
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

function TriggerCard({ t, variant }) {
  const isHighPri = (t.priority || 5) >= 8;
  const color = variant === "processing" ? "var(--warning)" :
    variant === "pending" ? "var(--agent-trigger)" :
    variant === "failed" ? "var(--error)" : "var(--success)";

  const style = {
    padding: isHighPri ? 14 : 10,
    border: "1px solid var(--border)",
    borderLeft: `${isHighPri ? 4 : 2}px solid ${color}`,
    borderRadius: "var(--radius-sm)",
    background: "var(--card)",
    boxShadow: isHighPri ? "0 2px 8px rgba(176,125,42,0.10)" : "none",
    animation: variant === "pending" ? "floatSoft 3s ease-in-out infinite" : "none",
  };

  return (
    <div style={style}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "DM Mono" }}>#{t.id}</span>
        {variant === "pending" && (
          <span style={{ fontSize: 11, fontWeight: 500, color }}>
            🔥 priority {t.priority}
          </span>
        )}
        <span className={`badge badge-${variant === "processing" ? "processing" : variant === "pending" ? "pending" : variant === "failed" ? "failed" : "completed"}`}>
          {variant}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {TYPE_LABEL[t.type] || t.type} · {t.strength}
        </span>
      </div>
      <div style={{ fontSize: isHighPri ? 15 : 13, fontWeight: isHighPri ? 500 : 400, lineHeight: 1.4 }}>
        {t.headline}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        {t.industry} · 来源 {t.source} · 引用 {t.source_news_ids?.length || 0} 条新闻
      </div>
      {t.consumed_by_run_id && (
        <div style={{ marginTop: 6, fontSize: 12 }}>
          → <Link to={`/runs/${t.consumed_by_run_id}`}>查看 run #{t.consumed_by_run_id}</Link>
        </div>
      )}
    </div>
  );
}
