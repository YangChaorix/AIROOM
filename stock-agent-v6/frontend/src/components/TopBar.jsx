import { useEffect, useState } from "react";
import { api } from "../lib/api";
import AgentAvatar from "./AgentAvatar";
import PromptEditorModal from "./PromptEditorModal";

const AGENT_ORDER = ["supervisor", "research", "screener", "skeptic", "trigger"];

export default function TopBar({ onToast }) {
  const [statuses, setStatuses] = useState([]);
  const [editingAgent, setEditingAgent] = useState(null);

  async function refresh() {
    try {
      const s = await api.agentsStatus();
      setStatuses(s);
    } catch {}
  }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const byName = Object.fromEntries(statuses.map((s) => [s.name, s]));

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--gap-md)", padding: "12px 20px", background: "var(--card)", borderBottom: "1px solid var(--border)" }}>
        <div style={{ fontSize: 16, fontWeight: 500, letterSpacing: 0.5 }}>
          Stock Agent <span style={{ color: "var(--primary)" }}>v6</span>
        </div>
        <div style={{ flex: "0 0 40px" }} />
        <div style={{ display: "flex", gap: 10 }}>
          {AGENT_ORDER.map((name) => {
            const s = byName[name];
            return (
              <AgentAvatar key={name} name={name} isActive={s?.is_active || false}
                lastActivity={s?.last_activity_at} onClick={() => setEditingAgent(name)} />
            );
          })}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>点 Agent 头像可编辑 prompt</div>
      </div>
      {editingAgent && (
        <PromptEditorModal agentName={editingAgent} onClose={() => setEditingAgent(null)} onToast={onToast} />
      )}
    </>
  );
}
