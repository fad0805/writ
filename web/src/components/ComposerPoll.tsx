"use client";

export default function ComposerPoll({ options, setOptions, expiresIn, setExpiresIn, lastRef }: {
  options: string[];
  setOptions: React.Dispatch<React.SetStateAction<string[]>>;
  expiresIn: number;
  setExpiresIn: React.Dispatch<React.SetStateAction<number>>;
  lastRef: React.MutableRefObject<HTMLInputElement | null>;
}) {
  return (
    <div style={{ marginBottom: 8, padding: 10, borderRadius: 8, background: "var(--bg-tertiary)" }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--text-secondary)" }}>투표</div>
      {options.map((opt, i) => (
        <div key={i} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
          <input
            ref={i === options.length - 1 ? lastRef : undefined}
            type="text" placeholder={`선택지 ${i + 1}`}
            value={opt} maxLength={50}
            onChange={(e) => {
              const next = [...options];
              next[i] = e.target.value;
              setOptions(next);
              // 마지막 칸에 내용이 생기면 빈 칸을 하나 추가하되, 포커스를 뺏지 않는다.
              // (포커스를 새 칸으로 옮기면 한 글자/자모마다 새 칸이 생기던 버그 방지)
              if (i === options.length - 1 && e.target.value.trim() && options.length < 10) {
                setOptions((prev) => prev.length < 10 && prev[prev.length - 1] !== "" ? [...prev, ""] : prev);
              }
            }}
            onKeyDown={(e) => {
              if (e.key !== "Enter" && e.key !== "Tab") return;
              if (e.key === "Tab" && e.shiftKey) {
                const prevInput = e.currentTarget.parentElement?.previousElementSibling?.querySelector<HTMLInputElement>("input");
                if (prevInput) { e.preventDefault(); prevInput.focus(); }
                return;
              }
              const nextInput = e.currentTarget.parentElement?.nextElementSibling?.querySelector<HTMLInputElement>("input");
              if (nextInput) {
                e.preventDefault();
                nextInput.focus();
              } else if (options[i].trim() && options.length < 10) {
                e.preventDefault();
                setOptions((prev) => [...prev, ""]);
                setTimeout(() => lastRef.current?.focus(), 0);
              } else if (e.key === "Enter") {
                e.preventDefault();
              }
            }}
            style={{ flex: 1, padding: "4px 8px", fontSize: 14, borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}
          />
          {options.length > 2 && (
            <button type="button" onClick={() => setOptions(options.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "var(--danger)", cursor: "pointer", fontSize: 16 }}>×</button>
          )}
        </div>
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
        {options.length < 10 && (
          <button type="button" className="action-btn" onClick={() => { setOptions([...options, ""]); setTimeout(() => lastRef.current?.focus(), 0); }} style={{ fontSize: 12 }}>+ 선택지 추가</button>
        )}
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>|</span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>마감</span>
        <select value={expiresIn} onChange={(e) => setExpiresIn(Number(e.target.value))} style={{ fontSize: 12, padding: "2px 4px", borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
          <option value={5}>5분</option>
          <option value={30}>30분</option>
          <option value={60}>1시간</option>
          <option value={360}>6시간</option>
          <option value={720}>12시간</option>
          <option value={1440}>24시간</option>
          <option value={4320}>3일</option>
          <option value={10080}>7일</option>
        </select>
      </div>
    </div>
  );
}
