/* 新闻流 Tab：News River —— 日期选择 + 来源下拉 + 消费状态 chip。 */
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import DatePicker, { toDateKey } from "../../components/DatePicker";

export default function NewsTab({ onToast }) {
  const [list, setList] = useState([]);
  const [stats, setStats] = useState(null);
  const [consumedFilter, setConsumedFilter] = useState("all"); // all / unconsumed / consumed
  const [source, setSource] = useState("");  // "" = 全部来源
  const [date, setDate] = useState(toDateKey(new Date()));
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);

  async function handleFetchAll() {
    setFetching(true);
    try {
      const res = await api.runAllChannels();
      onToast?.(`已触发 ${res.channels?.length || 0} 个渠道抓取（后台进行，去重已保证）`);
      setTimeout(refresh, 3000);
      setTimeout(refresh, 8000);
    } catch (e) {
      onToast?.(`触发失败：${e.message}`);
    } finally {
      setTimeout(() => setFetching(false), 3000);
    }
  }

  async function refresh() {
    setLoading(true);
    try {
      const params = { limit: 300, date };
      if (consumedFilter === "unconsumed") params.consumed = false;
      else if (consumedFilter === "consumed") params.consumed = true;
      if (source) params.source = source;
      setList(await api.listNews(params));
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => {
    api.newsStats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [consumedFilter, source, date]);

  const sources = stats ? Object.keys(stats.by_source) : [];

  return (
    <div className="card" style={{ height: "calc(100vh - 170px)", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--gap-sm)", flexWrap: "wrap", marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>📰 新闻流</h3>
        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
          {loading ? "刷新中…" : `${list.length} 条`}
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={handleFetchAll} disabled={fetching}
          style={{ fontSize: 12, padding: "5px 12px" }}>
          {fetching ? "抓取中…" : "🔄 立即抓取全部渠道"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <DatePicker value={date} onChange={setDate} />
        <span style={{ borderLeft: "1px solid var(--border)", height: 16 }} />
        <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>来源</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}
            style={{ padding: "4px 8px", fontSize: 12, borderRadius: 6,
              border: "1px solid var(--border)", background: "var(--card)",
              color: "var(--text)", cursor: "pointer" }}>
            <option value="">全部</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}{stats?.by_source?.[s] ? ` (${stats.by_source[s]})` : ""}
              </option>
            ))}
          </select>
        </div>
        <span style={{ borderLeft: "1px solid var(--border)", height: 16 }} />
        <Chip active={consumedFilter === "all"} onClick={() => setConsumedFilter("all")}>全部</Chip>
        <Chip active={consumedFilter === "unconsumed"} onClick={() => setConsumedFilter("unconsumed")} color="var(--agent-trigger)">
          🔵 未消费
        </Chip>
        <Chip active={consumedFilter === "consumed"} onClick={() => setConsumedFilter("consumed")} color="var(--success)">
          ✓ 已消费
        </Chip>
      </div>

      <div style={{ overflow: "auto", flex: 1 }}>
        {list.length === 0 ? (
          <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 40 }}>
            {loading ? "加载中…" : "该日期暂无新闻"}
          </div>
        ) : (
          list.map((n) => <NewsCard key={n.id} n={n} />)
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

