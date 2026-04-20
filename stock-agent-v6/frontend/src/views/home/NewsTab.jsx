/* 新闻流 Tab：News River —— 未消费/已消费过滤 chip + 时间段分组。 */
import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";

export default function NewsTab() {
  const [list, setList] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState("all"); // all / unconsumed / consumed / source:xxx
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const params = { limit: 200 };
      if (filter === "unconsumed") params.consumed = false;
      else if (filter === "consumed") params.consumed = true;
      else if (filter.startsWith("source:")) params.source = filter.slice(7);
      setList(await api.listNews(params));
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => {
    api.newsStats().then(setStats).catch(() => {});
    refresh();
    // eslint-disable-next-line
  }, [filter]);

  useEffect(() => {
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [filter]);

  const grouped = useMemo(() => groupByDay(list), [list]);

  const sources = stats ? Object.keys(stats.by_source) : [];

  return (
    <div className="card" style={{ height: "calc(100vh - 170px)", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--gap-sm)", flexWrap: "wrap", marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>📰 新闻流</h3>
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
          总 {stats?.total ?? 0} 条 · {loading ? "刷新中…" : `显示 ${list.length} 条`}
        </span>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "var(--gap-md)" }}>
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>全部</Chip>
        <Chip active={filter === "unconsumed"} onClick={() => setFilter("unconsumed")} color="var(--agent-trigger)">
          🔵 未消费
        </Chip>
        <Chip active={filter === "consumed"} onClick={() => setFilter("consumed")} color="var(--success)">
          ✓ 已消费
        </Chip>
        <span style={{ borderLeft: "1px solid var(--border)", margin: "0 4px" }} />
        {sources.map((s) => (
          <Chip key={s} active={filter === `source:${s}`} onClick={() => setFilter(`source:${s}`)}>
            {s}
          </Chip>
        ))}
      </div>

      <div style={{ overflow: "auto", flex: 1 }}>
        {Object.keys(grouped).length === 0 ? (
          <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 40 }}>
            {loading ? "加载中…" : "暂无新闻 · Scheduler 下次抓取时会滚入"}
          </div>
        ) : (
          Object.entries(grouped).map(([day, items]) => (
            <DayGroup key={day} day={day} items={items} />
          ))
        )}
      </div>
    </div>
  );
}

function Chip({ active, onClick, children, color }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 10px",
        border: "1px solid " + (active ? (color || "var(--primary)") : "var(--border)"),
        background: active ? (color || "var(--primary)") : "transparent",
        color: active ? "white" : "var(--text)",
        borderRadius: 14,
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function DayGroup({ day, items }) {
  return (
    <div style={{ marginBottom: "var(--gap-md)" }}>
      <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
        — {day} · {items.length} 条 —
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
        {items.map((n) => <NewsCard key={n.id} n={n} />)}
      </div>
    </div>
  );
}

function NewsCard({ n }) {
  const time = n.created_at ? new Date(n.created_at).toLocaleTimeString("zh-CN", { hour12: false }).slice(0, 5) : "";
  const consumed = !!n.consumed_by_trigger_id;

  return (
    <div style={{
      padding: 10,
      border: "1px solid var(--border)",
      borderLeft: "3px solid " + (consumed ? "var(--success)" : "var(--agent-trigger)"),
      borderRadius: "var(--radius-sm)",
      background: "var(--card)",
      animation: "slideInFromTop 0.25s ease-out",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "DM Mono" }}>{time}</span>
        <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "rgba(0,0,0,0.05)" }}>
          {n.source}
        </span>
        {consumed ? (
          <span style={{ fontSize: 10, color: "var(--success)" }}>
            ✓ 已消费 → trigger #{n.consumed_by_trigger_id}
          </span>
        ) : (
          <span style={{ fontSize: 10, color: "var(--agent-trigger)" }}>🔵 未消费</span>
        )}
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.4 }}>{n.title}</div>
      {n.content_preview && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          {n.content_preview.slice(0, 100)}
        </div>
      )}
    </div>
  );
}

function groupByDay(items) {
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();
  const groups = {};
  for (const it of items) {
    const d = new Date(it.created_at);
    const key = d.toDateString() === today ? "今日" :
      d.toDateString() === yesterday ? "昨日" :
      `${d.getMonth() + 1}/${d.getDate()}`;
    if (!groups[key]) groups[key] = [];
    groups[key].push(it);
  }
  return groups;
}
