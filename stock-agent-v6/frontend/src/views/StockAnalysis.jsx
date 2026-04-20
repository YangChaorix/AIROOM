/* 个股视图：启动单股分析（真时间线在 /runs/:id 内看）+ 历史列表（跨 run）+ 最近分析过的股票列表。
   URL 支持 ?code=300750 深链。启动后轮询最近 runs，找到 trigger_key=stock:<code> 的新 run → 提供链接。 */
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";

export default function StockAnalysis({ onToast }) {
  const [sp, setSp] = useSearchParams();
  const urlCode = sp.get("code") || "";

  const [input, setInput] = useState(urlCode);
  const [peers, setPeers] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingPid, setPendingPid] = useState(null);
  const [pendingCode, setPendingCode] = useState(null);
  const [launchedRun, setLaunchedRun] = useState(null);

  const [recentStocks, setRecentStocks] = useState([]);
  const [selectedCode, setSelectedCode] = useState(urlCode);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const pollRef = useRef(null);

  // ── 左栏：最近分析过的股票（从 /api/runs 里挖 trigger_key=stock:xxx） ──
  async function loadRecentStocks() {
    try {
      const runs = await api.listRuns(50);
      const map = new Map();
      for (const r of runs) {
        if (r.trigger_key?.startsWith("stock:")) {
          const code = r.trigger_key.slice(6);
          if (!map.has(code)) map.set(code, { code, last_run_id: r.id, last_status: r.status, last_at: r.started_at });
        }
      }
      setRecentStocks([...map.values()].slice(0, 12));
    } catch {}
  }
  useEffect(() => { loadRecentStocks(); }, []);

  // ── 右栏：选中股票的历史 ──
  useEffect(() => {
    if (!selectedCode) { setHistory([]); return; }
    setHistoryLoading(true);
    api.getStockHistory(selectedCode, 30)
      .then(setHistory)
      .catch(() => setHistory([]))
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
      setPendingCode(/^\d{6}$/.test(target) ? target : null); // 若是 code 直接锁定，否则等 run 出来
      onToast?.(`已启动 pid=${r.pid}，正在查找对应 run…`);
      // 轮询 runs 找 trigger_key=stock:<code>
      startPolling(target);
    } catch (e) {
      onToast?.(`启动失败：${e.message}`);
    } finally {
      setTimeout(() => setBusy(false), 1000);
    }
  }

  function startPolling(target) {
    if (pollRef.current) clearInterval(pollRef.current);
    const t0 = Date.now();
    pollRef.current = setInterval(async () => {
      // 最多等 30s；或者先找到 running 的 stock run
      if (Date.now() - t0 > 30_000) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        return;
      }
      try {
        const runs = await api.listRuns(10);
        // 找 started_at > 10s 内 + trigger_key 含 target
        const hit = runs.find((r) => r.trigger_key?.includes(target) && (Date.now() - new Date(r.started_at).getTime()) < 60_000);
        if (hit) {
          setLaunchedRun(hit);
          const codeMatch = hit.trigger_key.match(/^stock:(\d{6})$/);
          if (codeMatch) {
            setSelectedCode(codeMatch[1]);
            setSp({ code: codeMatch[1] });
          }
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
    setSp({ code });
    setInput(code);
  }

  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      {/* 启动栏 */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>🔍 分析个股</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="输入 6 位代码或股票名，例如 300750 或 宁德时代"
            onKeyDown={(e) => e.key === "Enter" && !busy && handleStart()}
            style={{ flex: 1, minWidth: 240, padding: "8px 12px", border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)", background: "var(--bg)" }} />
          <label style={{ fontSize: 12, color: "var(--text-muted)" }}>
            <input type="checkbox" checked={peers} onChange={(e) => setPeers(e.target.checked)} /> 带对标股
          </label>
          <button className="btn" disabled={busy || !input.trim()} onClick={handleStart}>
            {busy ? "启动中…" : "🚀 分析"}
          </button>
        </div>
        {pendingPid && !launchedRun && (
          <div style={{ marginTop: 10, padding: 10, borderRadius: 4, background: "rgba(200,137,46,0.08)",
            fontSize: 12, color: "var(--warning)", display: "flex", alignItems: "center", gap: 8 }}>
            <span className="dots" style={{ color: "var(--warning)" }}><span /><span /><span /></span>
            pid={pendingPid} 已启动，正在等待 run 在 DB 中创建（每 2s 轮询）…
          </div>
        )}
        {launchedRun && (
          <div style={{ marginTop: 10, padding: 10, borderRadius: 4, background: "rgba(91,138,58,0.10)",
            fontSize: 13, color: "var(--success)", display: "flex", alignItems: "center", gap: 8 }}>
            ✓ 已关联 run #{launchedRun.id}（<span className={`badge badge-${launchedRun.status}`}>{launchedRun.status}</span>）
            · <Link to={`/runs/${launchedRun.id}`}>查看实时时间线 →</Link>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "var(--gap-md)", minHeight: 400 }}>
        {/* 左栏：最近分析过的股票 */}
        <div className="card" style={{ height: "fit-content" }}>
          <h4 style={{ marginTop: 0 }}>📚 最近分析</h4>
          {recentStocks.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 12 }}>暂无历史 · 启动一次分析后会显示在此</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {recentStocks.map((s) => (
                <div key={s.code} onClick={() => selectStock(s.code)}
                  style={{ padding: "6px 10px", cursor: "pointer",
                    border: "1px solid " + (selectedCode === s.code ? "var(--primary)" : "var(--border)"),
                    borderRadius: "var(--radius-sm)",
                    background: selectedCode === s.code ? "rgba(176,125,42,0.08)" : "transparent" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontFamily: "DM Mono", fontSize: 13, fontWeight: 500 }}>{s.code}</span>
                    <span className={`badge badge-${s.last_status}`} style={{ fontSize: 10 }}>{s.last_status}</span>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                    最近 run #{s.last_run_id}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 右栏：历史分析时间线 */}
        <div className="card">
          {!selectedCode ? (
            <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 60, fontSize: 13 }}>
              ← 选择左侧股票查看历史 · 或输入代码启动新分析
            </div>
          ) : historyLoading ? (
            <div style={{ color: "var(--text-muted)" }}>加载中…</div>
          ) : history.length === 0 ? (
            <>
              <h3 style={{ marginTop: 0 }}>{selectedCode} · 暂无历史</h3>
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                这只股票尚未在任何 run 中出现过。上方启动一次分析会落盘。
              </div>
            </>
          ) : (
            <StockHistory code={selectedCode} history={history} />
          )}
        </div>
      </div>
    </div>
  );
}

function StockHistory({ code, history }) {
  const latest = history[0];
  const name = latest?.name || code;
  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>{name}</h3>
        <span style={{ fontFamily: "DM Mono", color: "var(--text-muted)" }}>{code}</span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>· {history.length} 条历史推荐</span>
      </div>

      <LatestCard row={latest} />

      <div style={{ marginTop: "var(--gap-md)" }}>
        <h4 style={{ marginTop: 0, color: "var(--text-muted)", fontSize: 13 }}>🕰️ 历史轨迹</h4>
        <div style={{ position: "relative", paddingLeft: 20 }}>
          <div style={{ position: "absolute", left: 7, top: 6, bottom: 6, width: 2, background: "var(--border)" }} />
          {history.map((h, i) => <HistoryRow key={i} h={h} />)}
        </div>
      </div>
    </>
  );
}

function LatestCard({ row }) {
  if (!row) return null;
  const strengths = parseJson(row.key_strengths_json);
  const risks = parseJson(row.key_risks_json);
  const color = row.level === "recommend" ? "var(--success)" : row.level === "watch" ? "var(--warning)" : "var(--text-muted)";
  return (
    <div style={{
      border: "1px solid var(--border)", borderLeft: `4px solid ${color}`,
      borderRadius: "var(--radius-sm)", padding: 12, marginTop: 8, background: "var(--card)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>最新</span>
        <span className={`badge badge-${row.level}`}>{row.level}</span>
        <span style={{ fontWeight: 500, color }}>{row.total_score?.toFixed(2)}</span>
        <RoleBadge role={row.role} />
        <span style={{ flex: 1 }} />
        <Link to={`/runs/${row.run_id}`} style={{ fontSize: 12 }}>run #{row.run_id} →</Link>
      </div>
      {row.recommendation_rationale && (
        <div style={{ fontSize: 13, lineHeight: 1.5 }}>💬 {row.recommendation_rationale}</div>
      )}
      {(strengths.length > 0 || risks.length > 0) && (
        <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
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
  );
}

function HistoryRow({ h }) {
  const t = h.rec_created_at ? new Date(h.rec_created_at) : null;
  const color = h.level === "recommend" ? "var(--success)" : h.level === "watch" ? "var(--warning)" : "var(--text-muted)";
  return (
    <div style={{ position: "relative", marginBottom: 10, animation: "slideInFromTop 0.2s ease-out" }}>
      <div style={{ position: "absolute", left: -17, top: 8, width: 10, height: 10, borderRadius: "50%",
        background: color, border: "2px solid var(--bg)" }} />
      <Link to={`/runs/${h.run_id}`} style={{ textDecoration: "none", color: "var(--text)" }}>
        <div style={{ padding: "6px 10px", border: "1px solid var(--border)", borderLeft: `3px solid ${color}`,
          borderRadius: "var(--radius-sm)", background: "var(--card)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
            <span style={{ color: "var(--text-muted)" }}>
              {t ? `${t.getMonth() + 1}/${t.getDate()} ${t.getHours().toString().padStart(2, "0")}:${t.getMinutes().toString().padStart(2, "0")}` : ""}
            </span>
            <span className={`badge badge-${h.level}`}>{h.level}</span>
            <span style={{ fontWeight: 500, color }}>{h.total_score?.toFixed(2)}</span>
            <RoleBadge role={h.role} />
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>run #{h.run_id}</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.4 }}>
            {h.trigger_headline}
          </div>
        </div>
      </Link>
    </div>
  );
}

function RoleBadge({ role }) {
  const map = {
    primary: { label: "主角", color: "var(--primary)" },
    peer:    { label: "对标", color: "var(--text-muted)" },
    candidate: { label: "候选", color: "var(--agent-screener)" },
  };
  const cfg = map[role] || { label: role, color: "var(--text-muted)" };
  return (
    <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8,
      border: `1px solid ${cfg.color}`, color: cfg.color }}>{cfg.label}</span>
  );
}

function parseJson(s) {
  if (!s) return [];
  try { const v = JSON.parse(s); return Array.isArray(v) ? v : []; }
  catch { return []; }
}
