import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { api } from "../lib/api";

export default function PromptEditorModal({ agentName, onClose, onToast }) {
  const [loading, setLoading] = useState(true);
  const [content, setContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [comment, setComment] = useState("");
  const [active, setActive] = useState(null);
  const [history, setHistory] = useState([]);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await api.getPrompt(agentName);
      setActive(data.active);
      setHistory(data.history || []);
      setContent(data.active?.content || "");
      setDirty(false); setComment("");
    } catch (e) {
      onToast?.(`加载失败：${e.message}`);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [agentName]);

  async function handleSave() {
    setSaving(true);
    try {
      const r = await api.savePrompt(agentName, content, comment || null);
      onToast?.(`已保存新版本 v${r.version_code}`);
      await load();
    } catch (e) { onToast?.(`保存失败：${e.message}`); }
    finally { setSaving(false); }
  }

  async function handleRollback(versionCode) {
    if (!confirm(`确定回滚到 ${versionCode}？会创建一个复制该内容的新版本。`)) return;
    try {
      const r = await api.rollbackPrompt(agentName, versionCode);
      onToast?.(`已回滚 · 新版本 v${r.new_version_code}`);
      await load();
    } catch (e) { onToast?.(`回滚失败：${e.message}`); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>
            ✏️ 编辑 <span style={{ color: `var(--agent-${agentName})` }}>{agentName}</span> Prompt
          </h3>
          <button onClick={onClose} style={{ background: "transparent", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        {loading ? (
          <div style={{ padding: "var(--gap-lg)", textAlign: "center" }}>加载中…</div>
        ) : (
          <>
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
              当前激活：<code>v{active?.version_code}</code> · 作者 {active?.author || "?"}
              {active?.comment ? ` · ${active.comment}` : ""}
            </div>
            <div style={{ marginTop: "var(--gap-sm)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", flex: "1 1 auto", minHeight: 300 }}>
              <Editor
                height="360px" language="markdown" value={content}
                onChange={(v) => { setContent(v || ""); setDirty(true); }}
                options={{ minimap: { enabled: false }, wordWrap: "on", fontSize: 13, lineNumbers: "off", scrollBeyondLastLine: false }}
              />
            </div>
            <div style={{ marginTop: "var(--gap-sm)" }}>
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>保存前备注（可选）：</label>
              <input type="text" value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder="如：调整 ReAct 约束"
                style={{ width: "100%", marginTop: 4, padding: 6, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--bg)" }} />
            </div>
            <details style={{ marginTop: "var(--gap-sm)" }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>📜 历史版本（{history.length}）</summary>
              <div style={{ maxHeight: 140, overflow: "auto", marginTop: 6 }}>
                {history.map((h) => (
                  <div key={h.version_code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 8px", borderBottom: "1px dashed var(--border)", fontSize: 12 }}>
                    <span>{h.is_active ? "⦿" : "○"} <code>v{h.version_code}</code> · {h.author} · {h.comment || "（无备注）"}</span>
                    {!h.is_active && (
                      <button className="btn-secondary" style={{ fontSize: 11, padding: "2px 8px" }} onClick={() => handleRollback(h.version_code)}>回滚</button>
                    )}
                  </div>
                ))}
              </div>
            </details>
            <div style={{ marginTop: "var(--gap-md)", display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button className="btn-secondary" onClick={onClose}>取消</button>
              <button className="btn" disabled={!dirty || saving} onClick={handleSave}>
                {saving ? "保存中…" : "保存（生成新版本）"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
