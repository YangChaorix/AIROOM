/* 个股视图：搜索/启动分析 + 最近分析过的股票列表 + 选中股票的最新分析结果。
   历史 runs 通过右上角"📋 历史"按钮在弹窗中查看。 */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import RunTimelineModal from "../components/RunTimelineModal";

export default function StockAnalysis({ onToast }) {
  const [sp, setSp] = useSearchParams();
  const urlCode = sp.get("code") || "";

  const [input, setInput]           = useState(urlCode);
  const [peers, setPeers]           = useState(true);
  const [busy, setBusy]             = useState(false);
  const [pendingPid, setPendingPid] = useState(null);
  const [launchedRun, setLaunchedRun] = useState(null);

  const [recentStocks, setRecentStocks] = useState([]);
  const [selectedCode, setSelectedCode] = useState(urlCode);
  const [stockRuns, setStockRuns]       = useState([]); // 该股 all runs（from history）
  const [latestRec, setLatestRec]       = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [timelineRunId, setTimelineRunId]   = useState(null);

  const pollRef = useRef(null);

  // ── 最近分析过的股票（从 runs 里挖 trigger_key=stock:xxx）──
  async function loadRecentStocks() {
    try {
      const runs = await api.listRuns(60);
      const map = new Map();
      for (const r of runs) {
        if (r.trigger_key?.startsWith("stock:")) {
          const code = r.trigger_key.slice(6);
          if (!map.has(code))
            map.set(code, { code, last_run_id: r.id, last_status: r.status, last_at: r.started_at });
        }
      }
      setRecentStocks([...map.values()].slice(0, 15));
    } catch {}
  }
  useEffect(() => { loadRecentStocks(); }, []);

  // ── 选中股票 → 拉历史 ──
  useEffect(() => {
    if (!selectedCode) { setStockRuns([]); setLatestRec(null); return; }
    setHistoryLoading(true);
    api.getStockHistory(selectedCode, 20)
      .then((rows) => {
        setStockRuns(rows);
        setLatestRec(rows[0] || null);
      })
      .catch(() => { setStockRuns([]); setLatestRec(null); })
      .finally(() => setHistoryLoading(false));
  }, [selectedCode]);

  // ── 启动分析 ──
  async function handleStart() {
    const target = input.trim();
    if (!target) return;
    setBusy(true);
    setLaunchedRun(null);
    try {
      const r = await api.startStock(target, peers);
      setPendingPid(r.pid);
      onToast?.(`已启动 pid=${r.pid}，正在等待 run 创建…`);
      startPolling(target);
    } catch (e) { onToast?.(`启动失败：${e.message}`); }
    finally { setTimeout(() => setBusy(false), 1000); }
  }

  function startPolling(target) {
    if (pollRef.current) clearInterval(pollRef.current);
    const t0 = Date.now();
    pollRef.current = setInterval(async () => {
      if (Date.now() - t0 > 30_000) { clearInterval(pollRef.current); return; }
      try {
        const runs = await api.listRuns(10);
        const hit = runs.find(
          (r) => r.trigger_key?.includes(target) && Date.now() - new Date(r.started_at).getTime() < 60_000
        );
        if (hit) {
          setLaunchedRun(hit);
          const codeMatch = hit.trigger_key.match(/^stock:(\d{6})$/);
          if (codeMatch) { selectStock(codeMatch[1]); }
          loadRecentStocks();
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {}
    }, 2000);
  }
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  function selectStock(code) {
    setSelectedCode(code);
    setInput(code);
    setSp({ code });
    setLaunchedRun(null);
    setPendingPid(null);
  }

  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      {/* 启动栏 */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>🔍 个股分析</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input type="text" value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入 6 位代码或股票名，例如 300750 或 宁德时代"
            onKeyDown={(e) => e.key === "Enter" && !busy && handleStart()}
            style={{ flex: 1, minWidth: 240, padding: "8px 12px",
              border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--bg)" }} />
          <label style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={peers} onChange={(e) => setPeers(e.target.checked)} /> 带对标股
          </label>
          <button className="btn" disabled={busy || !input.trim()} onClick={handleStart}>
            {busy ? "启动中…" : "🚀 分析"}
          </button>
        </div>
        {pendingPid && !launchedRun && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)",
            display: "flex", alignItems: "center", gap: 6 }}>
            <span className="dots" style={{ color: "var(--warning)" }}><span /><span /><span /></span>
            pid={pendingPid} 运行中，等待 run 创建…
          </div>
        )}
        {launchedRun && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--success)",
            display: "flex", alignItems: "center", gap: 8 }}>
            ✓ 已关联 run #{launchedRun.id}（
            <span className={`badge badge-${launchedRun.status}`}>{launchedRun.status}</span>）
            <button onClick={() => setTimelineRunId(launchedRun.id)}
              style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10, cursor: "pointer",
                border: "1px solid var(--success)", background: "transparent", color: "var(--success)" }}>
              ⏱ 查看执行过程
            </button>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: "var(--gap-md)", alignItems: "start" }}>
        {/* 左栏：最近分析的股票 */}
        <div className="card">
          <h4 style={{ marginTop: 0 }}>📚 最近分析</h4>
          {recentStocks.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无 · 启动分析后显示</div>
          ) : recentStocks.map((s) => (
            <div key={s.code} onClick={() => selectStock(s.code)}
              style={{ padding: "7px 10px", cursor: "pointer", marginBottom: 4,
                border: "1px solid " + (selectedCode === s.code ? "var(--primary)" : "var(--border)"),
                borderRadius: "var(--radius-sm)",
                background: selectedCode === s.code ? "rgba(176,125,42,0.08)" : "transparent" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontFamily: "DM Mono", fontSize: 13, fontWeight: 500 }}>{s.code}</span>
                <span className={`badge badge-${s.last_status}`} style={{ fontSize: 10 }}>{s.last_status}</span>
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 1 }}>run #{s.last_run_id}</div>
            </div>
          ))}
        </div>

        {/* 右栏：分析结果 */}
        <div>
          {!selectedCode ? (
            <div className="card" style={{ textAlign: "center", padding: 60, color: "var(--text-muted)", fontSize: 13 }}>
              ← 选择左侧股票 · 或输入代码启动新分析
            </div>
          ) : historyLoading ? (
            <div className="card" style={{ color: "var(--text-muted)" }}>加载中…</div>
          ) : !latestRec ? (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>{selectedCode}</h3>
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                暂无分析记录，点击上方"🚀 分析"启动
              </div>
            </div>
          ) : (
            <StockResult
              code={selectedCode}
              rec={latestRec}
              historyCount={stockRuns.length}
              onShowHistory={() => {
                const latestRunId = stockRuns[0]?.run_id;
                if (latestRunId) setTimelineRunId(latestRunId);
              }}
              onShowRun={(runId) => setTimelineRunId(runId)}
              allRuns={stockRuns}
            />
          )}
        </div>
      </div>

      {timelineRunId && (
        <RunTimelineModal runId={timelineRunId} onClose={() => setTimelineRunId(null)} />
      )}
    </div>
  );
}

function StockResult({ code, rec, historyCount, onShowHistory, onShowRun, allRuns }) {
  const [showAllRuns, setShowAllRuns] = useState(false);
  const color = rec.level === "recommend" ? "var(--success)" : rec.level === "watch" ? "var(--warning)" : "var(--text-muted)";
  const strengths = parseJson(rec.key_strengths_json);
  const risks     = parseJson(rec.key_risks_json);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap-sm)" }}>
      {/* 主卡片：最新分析结果 */}
      <div className="card" style={{ borderLeft: `4px solid ${color}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>{rec.name || code}</h3>
          <span style={{ fontFamily: "DM Mono", color: "var(--text-muted)", fontSize: 12 }}>{code}</span>
          <span className={`badge badge-${rec.level}`}>{rec.level === "recommend" ? "推荐" : rec.level === "watch" ? "观察" : "跳过"}</span>
          <span style={{ fontWeight: 600, color, fontSize: 16 }}>{rec.total_score?.toFixed(2)}</span>
          <RoleBadge role={rec.role} />
          <span style={{ flex: 1 }} />
          <button onClick={onShowHistory}
            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 12, cursor: "pointer",
              border: "1px solid var(--border)", background: "transparent", color: "var(--text-muted)" }}>
            ⏱ 执行历史
          </button>
        </div>

        {rec.trigger_headline && (
          <div style={{ fontSize: 12, color: "var(--agent-trigger)", marginBottom: 8,
            padding: "4px 8px", borderRadius: 4, background: "rgba(58,107,138,0.06)" }}>
            📡 {rec.trigger_headline}
          </div>
        )}

        {rec.recommendation_rationale && (
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>💬 {rec.recommendation_rationale}</div>
        )}

        {(strengths.length > 0 || risks.length > 0) && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 10 }}>
            {strengths.map((s, i) => (
              <span key={`s${i}`} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
                background: "rgba(91,138,58,0.12)", color: "var(--success)" }}>✓ {s}</span>
            ))}
            {risks.map((s, i) => (
              <span key={`r${i}`} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
                background: "rgba(180,74,58,0.10)", color: "var(--error)" }}>⚠ {s}</span>
            ))}
          </div>
        )}
      </div>

      {/* 历史轨迹折叠 */}
      {historyCount > 1 && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>历史推荐轨迹</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{historyCount} 条</span>
            <span style={{ flex: 1 }} />
            <button onClick={() => setShowAllRuns(!showAllRuns)}
              style={{ fontSize: 11, padding: "2px 10px", borderRadius: 12, cursor: "pointer",
                border: "1px solid var(--border)", background: "transparent", color: "var(--text-muted)" }}>
              {showAllRuns ? "▾ 收起" : "▸ 展开"}
            </button>
          </div>
          {showAllRuns && (
            <div style={{ marginTop: 10, position: "relative", paddingLeft: 18 }}>
              <div style={{ position: "absolute", left: 6, top: 4, bottom: 4,
                width: 2, background: "var(--border)" }} />
              {allRuns.map((h, i) => (
                <HistoryRow key={i} h={h} onShowRun={onShowRun} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HistoryRow({ h, onShowRun }) {
  const t = h.rec_created_at ? new Date(h.rec_created_at) : null;
  const color = h.level === "recommend" ? "var(--success)" : h.level === "watch" ? "var(--warning)" : "var(--text-muted)";
  return (
    <div style={{ position: "relative", marginBottom: 8 }}>
      <div style={{ position: "absolute", left: -15, top: 7,
        width: 9, height: 9, borderRadius: "50%", background: color, border: "2px solid var(--bg)" }} />
      <div style={{ padding: "5px 8px", border: "1px solid var(--border)",
        borderLeft: `3px solid ${color}`, borderRadius: "var(--radius-sm)", background: "var(--card)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
          <span style={{ color: "var(--text-muted)" }}>
            {t ? `${t.getMonth()+1}/${t.getDate()} ${String(t.getHours()).padStart(2,"0")}:${String(t.getMinutes()).padStart(2,"0")}` : ""}
          </span>
          <span className={`badge badge-${h.level}`} style={{ fontSize: 10 }}>{h.level}</span>
          <span style={{ fontWeight: 500, color }}>{h.total_score?.toFixed(2)}</span>
          <RoleBadge role={h.role} />
          <span style={{ flex: 1, fontSize: 11, color: "var(--text-muted)" }}>{h.trigger_headline?.slice(0, 30)}</span>
          <button onClick={() => onShowRun(h.run_id)}
            style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, cursor: "pointer",
              border: "1px solid var(--border)", background: "transparent", color: "var(--text-muted)" }}>
            ⏱ run #{h.run_id}
          </button>
        </div>
      </div>
    </div>
  );
}

function RoleBadge({ role }) {
  const map = { primary: ["主角", "var(--primary)"], peer: ["对标", "var(--text-muted)"], candidate: ["候选", "var(--agent-screener)"] };
  const [label, color] = map[role] || [role, "var(--text-muted)"];
  return (
    <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8,
      border: `1px solid ${color}`, color }}>{label}</span>
  );
}

function parseJson(s) {
  if (!s) return [];
  try { const v = JSON.parse(s); return Array.isArray(v) ? v : []; }
  catch { return []; }
}
