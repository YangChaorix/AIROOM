/* 配置视图：用户条件整体编辑态 + 新闻渠道开关/cron 编辑。 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function Config({ onToast }) {
  const [tab, setTab] = useState("conditions");
  return (
    <div style={{ padding: "var(--gap-md)", display: "flex", flexDirection: "column", gap: "var(--gap-md)" }}>
      <div style={{ display: "flex", gap: 6, borderBottom: "1px solid var(--border)", paddingBottom: 0 }}>
        <TabBtn active={tab === "conditions"} onClick={() => setTab("conditions")}>⚖️ 用户条件</TabBtn>
        <TabBtn active={tab === "channels"}   onClick={() => setTab("channels")}>📡 新闻渠道</TabBtn>
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
  trigger:  { label: "触发层", color: "var(--agent-trigger)",  hint: "Trigger Agent 关键词匹配 · 无权重" },
  screener: { label: "评估层", color: "var(--agent-screener)", hint: "Screener 条件打分 · 权重和应为 1.00" },
  entry:    { label: "入场层", color: "var(--warning)",         hint: "入场技术条件 · 权重和应为 1.00" },
};

let _newSeq = 0; // 草稿新条件的临时 key

function ConditionsTab({ onToast }) {
  const [saved,    setSaved]    = useState([]);
  const [draft,    setDraft]    = useState([]);
  const [editMode, setEditMode] = useState(false);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);

  async function refresh() {
    setLoading(true);
    try { setSaved(await api.listConditions()); }
    catch (e) { onToast?.(`加载失败：${e.message}`); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  function enterEdit() {
    setDraft(saved.map((c) => ({ ...c, _isNew: false, keywords: c.keywords ? [...c.keywords] : [] })));
    setEditMode(true);
  }
  function cancelEdit() { setEditMode(false); setDraft([]); }

  function updateDraft(tmpId, field, value) {
    setDraft((prev) => prev.map((c) => c._tmpId === tmpId ? { ...c, [field]: value } : c));
  }

  function addDraftRow(layer) {
    _newSeq++;
    const tmpId = `__new_${_newSeq}`;
    setDraft((prev) => [
      ...prev,
      { _tmpId: tmpId, _isNew: true, id: "", name: "", layer, description: "",
        weight: layer !== "trigger" ? 0 : null, keywords: [], active: true },
    ]);
  }

  function removeDraftRow(tmpId) {
    setDraft((prev) => prev.filter((c) => c._tmpId !== tmpId));
  }

  function validateWeights(conditions) {
    const errors = [];
    for (const layer of ["screener", "entry"]) {
      const active = conditions.filter((c) => c.layer === layer && c.active && !c._isNew);
      // 新增行暂时不纳入校验（id/name 可能还没填）
      if (active.length === 0) continue;
      const sum = active.reduce((s, c) => s + (parseFloat(c.weight) || 0), 0);
      if (Math.abs(sum - 1) > 0.01)
        errors.push(`${LAYER_LABEL[layer].label}权重合计 ${sum.toFixed(2)}，应为 1.00`);
    }
    // 新增行必须填 id 和 name
    const incompleteNew = draft.filter((c) => c._isNew && (!c.id.trim() || !c.name.trim()));
    if (incompleteNew.length > 0)
      errors.push(`有 ${incompleteNew.length} 个新增条件未填写 ID 或名称`);
    return errors;
  }

  async function saveAll() {
    const errs = validateWeights(draft);
    if (errs.length > 0) { onToast?.(`⚠ ${errs.join("；")}`); return; }

    setSaving(true);
    try {
      for (const c of draft) {
        const payload = { name: c.name, description: c.description, active: c.active,
          weight: c.weight, keywords: c.keywords };
        if (c._isNew) {
          await fetch("/api/conditions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: c.id.trim(), layer: c.layer, ...payload }),
          }).then((r) => r.ok ? r.json() : r.text().then((t) => Promise.reject(new Error(t))));
        } else {
          await api.updateCondition(c.id, payload);
        }
      }
      onToast?.("✓ 所有条件已保存");
      setEditMode(false);
      await refresh();
    } catch (e) { onToast?.(`保存失败：${e.message}`); }
    finally { setSaving(false); }
  }

  if (loading) return <div className="card">加载中…</div>;

  const display  = editMode ? draft : saved;
  const byLayer  = groupByLayer(display);

  return (
    <>
      {/* 头部工具栏 */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h3 style={{ margin: 0 }}>
            选股条件（{saved.length} · 启用 {saved.filter((c) => c.active).length}）
          </h3>
          <span style={{ flex: 1 }} />
          {!editMode ? (
            <button className="btn" onClick={enterEdit} style={{ fontSize: 12, padding: "5px 14px" }}>
              ✏️ 编辑
            </button>
          ) : (
            <>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>编辑中 · 修改完成后统一保存</span>
              <button className="btn-secondary" onClick={cancelEdit} style={{ fontSize: 12, padding: "5px 12px" }}>
                取消
              </button>
              <button className="btn" onClick={saveAll} disabled={saving} style={{ fontSize: 12, padding: "5px 14px" }}>
                {saving ? "保存中…" : "💾 保存"}
              </button>
            </>
          )}
        </div>
        {editMode && (
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--warning)" }}>
            ⚠ 评估层/入场层的启用条件权重之和必须等于 1.00，保存时自动验证
          </div>
        )}
      </div>

      {/* 三层条件分组 */}
      {Object.entries(LAYER_LABEL).map(([layer, cfg]) => {
        const items = byLayer[layer] || [];
        const existingActive = items.filter((c) => c.active && !c._isNew);
        const weightSum = existingActive.reduce((s, c) => s + (parseFloat(c.weight) || 0), 0);
        const weightOk  = layer === "trigger" || existingActive.length === 0 || Math.abs(weightSum - 1) < 0.01;

        return (
          <div key={layer} className="card">
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <h4 style={{ margin: 0, color: cfg.color }}>{cfg.label}（{items.filter((c) => !c._isNew).length}）</h4>
              {layer !== "trigger" && existingActive.length > 0 && (
                <span style={{ fontSize: 11, color: weightOk ? "var(--success)" : "var(--error)", fontWeight: weightOk ? 400 : 600 }}>
                  权重合计 {weightSum.toFixed(2)} {weightOk ? "✓" : "← 需调整为 1.00"}
                </span>
              )}
              <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>{cfg.hint}</span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {items.length === 0 && !editMode && (
                <div style={{ color: "var(--text-muted)", fontSize: 12 }}>此层暂无条件</div>
              )}
              {items.map((c) =>
                editMode
                  ? <ConditionRowEdit key={c._tmpId || c.id} c={c}
                      onChange={(f, v) => updateDraft(c._tmpId, f, v)}
                      onRemove={c._isNew ? () => removeDraftRow(c._tmpId) : null} />
                  : <ConditionRowView key={c.id} c={c} />
              )}
            </div>

            {/* 每层底部的添加按钮，仅编辑态显示 */}
            {editMode && (
              <button onClick={() => addDraftRow(layer)}
                style={{ marginTop: 8, width: "100%", padding: "6px 0", fontSize: 12,
                  border: "1px dashed var(--border)", borderRadius: "var(--radius-sm)",
                  background: "transparent", color: "var(--text-muted)", cursor: "pointer" }}>
                + 在{cfg.label}添加条件
              </button>
            )}
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

/* ── 查看态 ── */
function ConditionRowView({ c }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ padding: "8px 12px", border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)", opacity: c.active ? 1 : 0.5,
      background: c.active ? "var(--card)" : "rgba(0,0,0,0.02)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 10, padding: "1px 5px", borderRadius: 6,
          background: c.active ? "rgba(91,138,58,0.12)" : "rgba(0,0,0,0.06)",
          color: c.active ? "var(--success)" : "var(--text-muted)" }}>
          {c.active ? "启用" : "停用"}
        </span>
        <code style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--text-muted)", minWidth: 44 }}>{c.id}</code>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{c.name}</span>
        <span style={{ flex: 1 }} />
        {c.weight != null && (
          <span style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--primary)" }}>
            {c.weight.toFixed(2)}
          </span>
        )}
        <button onClick={() => setExpanded(!expanded)}
          style={{ background: "transparent", border: "none", cursor: "pointer",
            color: "var(--text-muted)", fontSize: 11, padding: "2px 4px" }}>
          {expanded ? "▾" : "▸"}
        </button>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--border)",
          fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
          {c.description}
          {c.keywords?.length > 0 && (
            <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
              {c.keywords.map((k, i) => (
                <span key={i} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10,
                  background: "rgba(58,107,138,0.10)", color: "var(--agent-trigger)" }}>{k}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── 编辑态 ── */
function ConditionRowEdit({ c, onChange, onRemove }) {
  const [expanded, setExpanded] = useState(!!c._isNew); // 新条件默认展开
  const isNew = c._isNew;
  return (
    <div style={{ padding: "10px 12px",
      border: `1px solid ${isNew ? "var(--primary)" : "var(--border)"}`,
      borderRadius: "var(--radius-sm)", background: isNew ? "rgba(176,125,42,0.04)" : "white",
      opacity: c.active ? 1 : 0.65 }}>
      {/* 首行 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Switch checked={c.active} onChange={(v) => onChange("active", v)} />
        {isNew ? (
          <input value={c.id} onChange={(e) => onChange("id", e.target.value)}
            placeholder="ID 如 C8"
            style={{ width: 72, fontFamily: "DM Mono", fontSize: 12,
              border: "1px solid var(--border)", borderRadius: 4,
              padding: "3px 6px", background: "var(--bg)", color: "var(--primary)" }} />
        ) : (
          <code style={{ fontFamily: "DM Mono", fontSize: 12, color: "var(--text-muted)", minWidth: 44 }}>{c.id}</code>
        )}
        <input value={c.name} onChange={(e) => onChange("name", e.target.value)}
          placeholder="条件名称（必填）"
          style={{ fontSize: 13, fontWeight: 500, border: "1px solid var(--border)",
            borderRadius: 4, padding: "3px 8px", flex: 1, background: "var(--bg)" }} />
        {c.layer !== "trigger" && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>权重</span>
            <input type="number" step="0.01" min="0" max="1"
              value={c.weight ?? ""} onChange={(e) => onChange("weight", parseFloat(e.target.value) || 0)}
              style={{ width: 60, fontFamily: "DM Mono", fontSize: 13, textAlign: "right",
                border: "1px solid var(--border)", borderRadius: 4, padding: "3px 6px",
                color: "var(--primary)", background: "var(--bg)" }} />
          </div>
        )}
        <button onClick={() => setExpanded(!expanded)}
          style={{ background: "transparent", border: "none", cursor: "pointer",
            color: "var(--text-muted)", fontSize: 11, padding: "2px 4px", flexShrink: 0 }}>
          {expanded ? "▾" : "▸"}
        </button>
        {onRemove && (
          <button onClick={onRemove} title="删除此新增条件"
            style={{ background: "transparent", border: "none", cursor: "pointer",
              color: "var(--error)", fontSize: 14, padding: "2px 4px", lineHeight: 1 }}>
            ✕
          </button>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--border)" }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>描述 / Prompt 片段（必填）</div>
          <textarea value={c.description || ""} rows={3}
            onChange={(e) => onChange("description", e.target.value)}
            placeholder="输入描述…"
            style={{ width: "100%", fontSize: 12, padding: "6px 8px",
              border: "1px solid var(--border)", borderRadius: 4,
              background: "var(--bg)", lineHeight: 1.5, resize: "vertical", fontFamily: "inherit" }} />
          {c.layer === "trigger" && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>关键词（逗号分隔）</div>
              <input value={(c.keywords || []).join(", ")}
                onChange={(e) => onChange("keywords", e.target.value.split(/[,，\s]+/).map((k) => k.trim()).filter(Boolean))}
                placeholder="政策落地, 补贴, 实施细则…"
                style={{ width: "100%", fontSize: 12, padding: "5px 8px",
                  border: "1px solid var(--border)", borderRadius: 4, background: "var(--bg)" }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ────────────── 公共小组件 ────────────── */

function Switch({ checked, onChange }) {
  return (
    <button onClick={() => onChange(!checked)} role="switch" aria-checked={checked}
      style={{ width: 32, height: 18, borderRadius: 10, border: "none", cursor: "pointer",
        background: checked ? "var(--success)" : "var(--text-muted)",
        padding: 0, position: "relative", transition: "background 0.2s", flexShrink: 0 }}>
      <span style={{ position: "absolute", top: 2, left: checked ? 16 : 2,
        width: 14, height: 14, borderRadius: "50%", background: "white",
        transition: "left 0.2s" }} />
    </button>
  );
}

const inputStyle = {
  padding: "6px 10px", fontSize: 13, border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)", background: "var(--bg)",
};

/* ────────────── Channels ────────────── */

function ChannelsTab({ onToast }) {
  const [cfg, setCfg]   = useState(null);
  const [busy, setBusy] = useState({});

  async function refresh() {
    try { setCfg(await api.listChannels()); }
    catch (e) { onToast?.(`加载失败：${e.message}`); }
  }
  useEffect(() => { refresh(); }, []);

  async function save(name, patch) {
    try { await api.updateChannel(name, patch); onToast?.(`✓ ${name} 已更新`); refresh(); }
    catch (e) { onToast?.(`保存失败：${e.message}`); }
  }

  async function runNow(name) {
    setBusy((b) => ({ ...b, [name]: true }));
    try { const r = await api.runChannel(name); onToast?.(`✓ ${name} 已启动（pid=${r.pid}）`); }
    catch (e) { onToast?.(`启动失败：${e.message}`); }
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
          点击 cron 值直接编辑 · APScheduler 语法（hour/minute/day_of_week）· 重启 scheduler 后生效
        </div>
      </div>
      {cfg.channels.map((c) => (
        <ChannelRow key={c.name} c={c} busy={busy[c.name]}
          onSave={(p) => save(c.name, p)} onRunNow={() => runNow(c.name)} />
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
      if (JSON.stringify(parsed) !== JSON.stringify(c.cron)) onSave({ cron: parsed });
    } catch {
      alert("cron JSON 格式错误");
      setCronDraft(JSON.stringify(c.cron));
    }
  }

  return (
    <div className="card" style={{ opacity: c.enabled ? 1 : 0.65 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Switch checked={c.enabled} onChange={(v) => onSave({ enabled: v })} />
        <code style={{ fontFamily: "DM Mono", fontSize: 13, fontWeight: 500 }}>{c.name}</code>
        <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10,
          background: "rgba(0,0,0,0.04)", color: "var(--text-muted)" }}>{c.source_label}</span>
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
      <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>cron:</span>
        {editingCron ? (
          <input autoFocus value={cronDraft} onChange={(e) => setCronDraft(e.target.value)}
            onBlur={commitCron} onKeyDown={(e) => e.key === "Enter" && e.target.blur()}
            style={{ fontFamily: "DM Mono", fontSize: 12, padding: "3px 8px", width: 280,
              border: "1px solid var(--primary)", borderRadius: 4, background: "white" }} />
        ) : (
          <code onClick={() => setEditingCron(true)} title="点击编辑"
            style={{ fontFamily: "DM Mono", fontSize: 12, cursor: "pointer",
              padding: "2px 8px", borderRadius: 4, background: "rgba(0,0,0,0.04)" }}>
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
  if (cron.hour      !== undefined) parts.push(`hour=${cron.hour}`);
  if (cron.minute    !== undefined) parts.push(`min=${cron.minute}`);
  if (cron.day_of_week !== undefined) parts.push(`dow=${cron.day_of_week}`);
  return parts.join(" ");
}
