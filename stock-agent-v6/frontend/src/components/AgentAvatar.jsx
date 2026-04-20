const AGENT_COLORS = {
  supervisor: "var(--agent-supervisor)",
  research:   "var(--agent-research)",
  screener:   "var(--agent-screener)",
  skeptic:    "var(--agent-skeptic)",
  trigger:    "var(--agent-trigger)",
};
const AGENT_LABELS = {
  supervisor: "S", research: "R", screener: "C", skeptic: "K", trigger: "T",
};
const AGENT_ZH = {
  supervisor: "Supervisor", research: "Research", screener: "Screener", skeptic: "Skeptic", trigger: "Trigger",
};

export default function AgentAvatar({ name, isActive, lastActivity, onClick }) {
  const color = AGENT_COLORS[name] || "#888";
  const initial = AGENT_LABELS[name] || "?";
  const zh = AGENT_ZH[name] || name;
  const title = `${zh}\n` + (isActive ? "工作中" : lastActivity ? `空闲 · 最近活动：${new Date(lastActivity).toLocaleString("zh-CN")}` : "空闲");
  return (
    <button
      className={`agent-avatar ${isActive ? "active" : "idle"}`}
      style={{ color, borderColor: isActive ? color : "var(--border)", background: isActive ? `${color}14` : "var(--card)" }}
      onClick={onClick}
      title={title}
    >
      {initial}
    </button>
  );
}
