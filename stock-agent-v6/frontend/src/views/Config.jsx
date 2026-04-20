/* 配置视图：用户条件 inline 编辑 + 新闻渠道开关/cron 编辑 + 立即抓取。
   AI-native 原则：点击字段立即进入编辑 → blur 自动保存 → toast 反馈，无需"保存"按钮。 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function Config({ onToast }) {
  const [tab, setTab] = useState("conditions");
  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <div style={{ display: "flex", gap: 6, borderBottom: "1px solid var(--border)", paddingBottom: 0 }}>
        <TabBtn active={tab === "conditions"} onClick={() => setTab("conditions")}>⚖️ 用户条件</TabBtn>
        <TabBtn active={tab === "channels"} onClick={() => setTab("channels")}>📡 新闻渠道</TabBtn>
      </div>
      {tab === "conditions" ? <ConditionsTab onToast={onToast} /> : <ChannelsTab onToast={onToast} />}
    </div>
  );
}

function TabBtn({ active, onClick, children }) {
  return (
    <button onClick={onClick}
      style={{ padding: "8px 16px", border: "none", background: "transparent",
        color: active ? "var(--primary)" : "var(--text-muted)",
        fontWeight: active ? 500 : 400,
        borderBottom: "2px solid " + (active ? "var(--primary)" : "transparent"),
        cursor: "pointer", fontSize: 14, marginBottom: -1 }}>
      {children}
    </button>
  );
}

/* ────────────── Conditions ────────────── */

const LAYER_LABEL = {
  trigger:  { label: "触发层", color: "var(--agent-trigger)", hint: "Trigger Agent 用的关键词匹配 · 无权重" },
  screener: { label: "评估层", color: "var(--agent-screener)", hint: "Screener 用的条件打分 · 需填权重" },
  entry:    { label: "入场层", color: "var(--warning)", hint: "Screener 用的入场技术条件 · 需填权重" },
};

function ConditionsTab({ onToast }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  async function refresh() {
    try { setList(await api.listConditions()); }
    catch (e) { onToast?.(`加载失败：${e.message}`); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  async function updateField(cond, field, value) {
    try {
      await api.updateCondition(cond.id, { [field]: value });
      onToast?.(`✓ ${cond.id} · ${field} 已更新`);
      refresh();
    } catch (e) { onToast?.(`保存失败：${e.message}`); }
  }

  async function addNew(payload) {
    try {
      await fetch("/api/conditions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => r.ok ? r.json() : r.text().then((t) => Promise.reject(new Error(t))));
      onToast?.(`✓ 新增条件 ${payload.id}`);
      setShowAdd(false);
      refresh();
    } catch (e) { onToast?.(`新增失败：${e.message}`); }
  }

  const byLayer = groupByLayer(list);
  const layerTotal = (layer) => byLayer[layer]?.filter((c) => c.active).reduce((s, c) => s + (c.weight || 0), 0) || 0;

  if (loading) return <div className="card">加载中…</div>;

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <h3 style={{ margin: 0 }}>选股条件（{list.length} · 启用 {list.filter((c) => c.active).length}）</h3>
          <button className="btn-secondary" onClick={() => setShowAdd(!showAdd)} style={{ fontSize: 12, padding: "5px 12px" }}>
            {showAdd ? "收起" : "+ 新增条件"}
          </button>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          点击权重/描述字段直接编辑 · 失焦自动保存 · 改权重后 Screener 下次运行立即生效
        </div>
      </div>

      {showAdd && <NewConditionForm onSave={addNew} onCancel={() => setShowAdd(false)} />}

      {Object.entries(LAYER_LABEL).map(([layer, cfg]) => {
        const items = byLayer[layer] || [];
        const total = layerTotal(layer);
        const weightValid = layer === "trigger" || Math.abs(total - 1) < 0.001;
        return (
          <div key={layer} className="card">
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
              <h4 style={{ margin: 0, color: cfg.color }}>
                {cfg.label}（{items.length}）
              </h4>
              {layer !== "trigger" && (
                <span style={{ fontSize: 11, color: weightValid ? "var(--success)" : "var(--error)" }}>
                  权重合计 {total.toFixed(2)} {weightValid ? "✓" : "(应为 1.00)"}
                </span>
              )}
              <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>{cfg.hint}</span>
            </div>

            {items.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12 }}>此层暂无条件</div>
            ) : items.map((c) => (
              <ConditionRow key={c.id} c={c} onUpdate={(f, v) => updateField(c, f, v)} />
            ))}
          </div>
        );
      })}
    </>
  );
}

function groupByLayer(list) {
  const g = {};
  for (const c of list) { (g[c.layer] ||= []).push(c); }
  return g;
}

function ConditionRow({ c, onUpdate }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{
      padding: "10px 12px", marginBottom: 6,
      border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
      background: c.active ? "var(--card)" : "rgba(0,0,0,0.02)",
      opacity: c.active ? 1 : 0.6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Switch checked={c.active} onChange={(v) => onUpdate("active", v)} />
        <code style={{ fontFamily: "DM Mono", fontSize: 13, fontWeight: 500, minWidth: 44 }}>{c.id}</code>
        <strong style={{ fontSize: 13 }}>{c.name}</strong>
        <span style={{ flex: 1 }} />
        {c.layer !== "trigger" && (
          <InlineWeight value={c.weight} onChange={(v) => onUpdate("weight", v)} />
        )}
        <button onClick={() => setExpanded(!expanded)}
          style={{ background: "transparent", border: "none", cursor: "pointer",
            color: "var(--text-muted)", fontSize: 11 }}>
          {expanded ? "▾" : "▸"}
        </button>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--border)",
          fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
          {c.description}
          {c.keywords && c.keywords.length > 0 && (
            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
              {c.keywords.map((k, i) => (
                <span key={i} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8,
                  background: "rgba(58,107,138,0.08)", color: "var(--agent-trigger)" }}>{k}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InlineWeight({ value, onChange }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => { setDraft(value ?? ""); }, [value]);

  function commit() {
    setEditing(false);
    const n = parseFloat(draft);
    if (isNaN(n) || n === value) return;
    onChange(n);
  }
  if (editing) {
    return (
      <input autoFocus type="number" step="0.01" min="0" max="1" value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.target.blur()}
        style={{ width: 60, padding: "2px 6px", fontSize: 12, fontFamily: "DM Mono",
          border: "1px solid var(--primary)", borderRadius: 4, background: "white" }} />
    );
  }
  return (
    <span onClick={() => setEditing(true)}
      style={{ fontFamily: "DM Mono", fontSize: 13, cursor: "pointer",
        padding: "2px 8px", borderRadius: 4, border: "1px dashed transparent",
        color: value != null ? "var(--primary)" : "var(--text-muted)" }}
      title="点击编辑">
      {value != null ? value.toFixed(2) : "—"}
    </span>
  );
}

function Switch({ checked, onChange }) {
  return (
    <button onClick={() => onChange(!checked)} role="switch" aria-checked={checked}
      style={{ width: 32, height: 18, borderRadius: 10, border: "none", cursor: "pointer",
        background: checked ? "var(--success)" : "var(--text-muted)", padding: 0,
        position: "relative", transition: "background 0.2s" }}>
      <span style={{ position: "absolute", top: 2, left: checked ? 16 : 2,
        width: 14, height: 14, borderRadius: "50%", background: "white",
        transition: "left 0.2s" }} />
    </button>
  );
}

function NewConditionForm({ onSave, onCancel }) {
  const [form, setForm] = useState({
    id: "", name: "", layer: "screener", description: "", weight: 0.1, keywords: "",
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  function submit() {
    if (!form.id.trim() || !form.name.trim() || !form.description.trim()) return;
    const payload = {
      id: form.id.trim(),
      name: form.name.trim(),
      layer: form.layer,
      description: form.description.trim(),
    };
    if (form.layer !== "trigger") payload.weight = parseFloat(form.weight) || 0;
    if (form.layer === "trigger") payload.keywords = form.keywords.split(/[,，\s]+/).filter(Boolean);
    onSave(payload);
  }

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--primary)" }}>
      <h4 style={{ marginTop: 0 }}>+ 新增条件</h4>
      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 140px", gap: 8, alignItems: "center" }}>
        <input placeholder="ID 如 C8" value={form.id} onChange={(e) => set("id", e.target.value)} style={inputStyle} />
        <input placeholder="名称 如 技术突破" value={form.name} onChange={(e) => set("name", e.target.value)} style={inputStyle} />
        <select value={form.layer} onChange={(e) => set("layer", e.target.value)} style={inputStyle}>
          <option value="trigger">trigger</option>
          <option value="screener">screener</option>
          <option value="entry">entry</option>
        </select>
        <textarea placeholder="描述 / Prompt 片段" value={form.description}
          onChange={(e) => set("description", e.target.value)}
          rows={2} style={{ ...inputStyle, gridColumn: "1 / 3", fontFamily: "inherit" }} />
        {form.layer !== "trigger" ? (
          <input type="number" step="0.01" placeholder="权重 0-1" value={form.weight}
            onChange={(e) => set("weight", e.target.value)} style={inputStyle} />
        ) : (
          <input placeholder="keywords 逗号分隔" value={form.keywords}
            onChange={(e) => set("keywords", e.target.value)} style={inputStyle} />
        )}
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <button className="btn" onClick={submit} disabled={!form.id || !form.name || !form.description}>
          保存
        </button>
        <button className="btn-secondary" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "6px 10px", fontSize: 13, border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)", background: "var(--bg)",
};

/* ────────────── Channels ────────────── */

function ChannelsTab({ onToast }) {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState({});

  async function refresh() {
    try { setCfg(await api.listChannels()); }
    catch (e) { onToast?.(`加载失败：${e.message}`); }
  }
  useEffect(() => { refresh(); }, []);

  async function save(name, patch) {
    try {
      await api.updateChannel(name, patch);
      onToast?.(`✓ ${name} 已更新`);
      refresh();
    } catch (e) { onToast?.(`保存失败：${e.message}`); }
  }

  async function runNow(name) {
    setBusy({ ...busy, [name]: true });
    try {
      const r = await api.runChannel(name);
      onToast?.(`✓ ${name} 已启动抓取（pid=${r.pid}）`);
    } catch (e) { onToast?.(`启动失败：${e.message}`); }
    finally { setTimeout(() => setBusy((b) => ({ ...b, [name]: false })), 1500); }
  }

  if (!cfg) return <div className="card">加载中…</div>;

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>新闻渠道（{cfg.channels.length} · 启用 {cfg.channels.filter((c) => c.enabled).length}）</h3>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>TZ {cfg.timezone}</span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          点击 cron JSON 直接编辑 · APScheduler 语法（hour/minute/day_of_week）· 改动后下次 scheduler 重启生效
        </div>
      </div>

      {cfg.channels.map((c) => (
        <ChannelRow key={c.name} c={c} busy={busy[c.name]}
          onSave={(patch) => save(c.name, patch)}
          onRunNow={() => runNow(c.name)} />
      ))}
    </>
  );
}

function ChannelRow({ c, busy, onSave, onRunNow }) {
  const [cronDraft, setCronDraft] = useState(JSON.stringify(c.cron));
  const [editingCron, setEditingCron] = useState(false);
  useEffect(() => { setCronDraft(JSON.stringify(c.cron)); }, [c.cron]);

  function commitCron() {
    setEditingCron(false);
    try {
      const parsed = JSON.parse(cronDraft);
      if (JSON.stringify(parsed) === JSON.stringify(c.cron)) return;
      onSave({ cron: parsed });
    } catch {
      alert("cron JSON 格式错误，请检查");
      setCronDraft(JSON.stringify(c.cron));
    }
  }

  return (
    <div className="card" style={{ opacity: c.enabled ? 1 : 0.65 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Switch checked={c.enabled} onChange={(v) => onSave({ enabled: v })} />
        <code style={{ fontFamily: "DM Mono", fontSize: 13, fontWeight: 500 }}>{c.name}</code>
        <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
          background: "rgba(0,0,0,0.04)", color: "var(--text-muted)" }}>
          {c.source_label}
        </span>
        {c.adapter && (
          <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8,
            background: "rgba(107,91,149,0.10)", color: "var(--agent-supervisor)" }}>
            adapter: {c.adapter}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button className="btn-secondary" disabled={busy} onClick={onRunNow}
          style={{ fontSize: 11, padding: "4px 10px" }}>
          {busy ? "抓取中…" : "▶ 立即抓取"}
        </button>
      </div>

      <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>cron:</span>
        {editingCron ? (
          <input autoFocus value={cronDraft} onChange={(e) => setCronDraft(e.target.value)}
            onBlur={commitCron}
            onKeyDown={(e) => e.key === "Enter" && e.target.blur()}
            style={{ fontFamily: "DM Mono", fontSize: 12, padding: "3px 8px", width: 280,
              border: "1px solid var(--primary)", borderRadius: 4, background: "white" }} />
        ) : (
          <code onClick={() => setEditingCron(true)}
            style={{ fontFamily: "DM Mono", fontSize: 12, cursor: "pointer",
              padding: "2px 8px", borderRadius: 4, background: "rgba(0,0,0,0.04)" }}
            title="点击编辑 JSON">
            {JSON.stringify(c.cron)}
          </code>
        )}
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>→ {cronDescribe(c.cron)}</span>
      </div>

      {c.description && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.4 }}>
          {c.description}
        </div>
      )}
    </div>
  );
}

function cronDescribe(cron) {
  if (!cron || typeof cron !== "object") return "";
  const parts = [];
  if (cron.hour !== undefined) parts.push(`hour=${cron.hour}`);
  if (cron.minute !== undefined) parts.push(`min=${cron.minute}`);
  if (cron.day_of_week !== undefined) parts.push(`dow=${cron.day_of_week}`);
  return parts.join(" ");
}
