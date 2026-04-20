/* 日期选择器：原生 <input type="date">，默认今天，max=今天。 */

export function toDateKey(isoOrDate) {
  const d = isoOrDate instanceof Date ? isoOrDate : new Date(isoOrDate);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function DatePicker({ value, onChange, max, label = "日期" }) {
  const today = toDateKey(new Date());
  const maxStr = max || today;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{label}</span>
      <input
        type="date"
        value={value || today}
        max={maxStr}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "4px 8px",
          fontSize: 12,
          border: "1px solid var(--border)",
          borderRadius: 6,
          background: "var(--card)",
          color: "var(--text)",
          fontFamily: "DM Mono",
          cursor: "pointer",
        }}
      />
      {value && value !== today && (
        <button
          onClick={() => onChange(today)}
          style={{
            fontSize: 11, padding: "3px 8px", borderRadius: 10, cursor: "pointer",
            border: "1px solid var(--border)", background: "transparent", color: "var(--text-muted)",
          }}
        >
          今天
        </button>
      )}
    </div>
  );
}
