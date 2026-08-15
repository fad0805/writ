"use client";

export default function ComposerMedia({ items, setItems, altIdx, setAltIdx, revokePreviews }: {
  items: { id: number; url: string; type: string; file?: File; alt?: string; preview?: string }[];
  setItems: React.Dispatch<React.SetStateAction<{ id: number; url: string; type: string; file?: File; alt?: string; preview?: string }[]>>;
  altIdx: number | null;
  setAltIdx: React.Dispatch<React.SetStateAction<number | null>>;
  revokePreviews: (items: { preview?: string }[]) => void;
}) {
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
        {items.map((m, i) => (
          <div key={m.id} draggable style={{ position: "relative", width: 80, height: 80 }}
            onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(i)); (e.currentTarget as HTMLElement).style.opacity = "0.4"; }}
            onDragEnd={(e) => { (e.currentTarget as HTMLElement).style.opacity = "1"; }}
            onDragOver={(e) => { e.preventDefault(); }}
            onDrop={(e) => { e.preventDefault(); const from = parseInt(e.dataTransfer.getData("text/plain")); const to = i; if (from !== to) { const c = [...items]; const [removed] = c.splice(from, 1); c.splice(to, 0, removed); setItems(c); } }}
          >
            {m.type === "video" ? (
              <video src={m.preview || m.url} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6, pointerEvents: "none" }} />
            ) : (
              <img src={m.preview || m.url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6, pointerEvents: "none" }} />
            )}
            <span onClick={(e) => { e.stopPropagation(); setAltIdx(i); }} style={{ position: "absolute", bottom: -4, right: -4, width: 18, height: 18, borderRadius: "50%", background: m.alt ? "var(--accent)" : "var(--bg-secondary)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontStyle: "italic", cursor: "pointer", color: m.alt ? "#fff" : "var(--text-muted)" }} title="미디어 설명">a</span>
            <span onClick={(e) => { e.stopPropagation(); revokePreviews(items.slice(i, i + 1)); setItems(items.filter((_, j) => j !== i)); }} style={{ position: "absolute", top: -4, right: -4, width: 18, height: 18, borderRadius: "50%", background: "var(--danger)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, cursor: "pointer" }}>×</span>
          </div>
        ))}
      </div>
      {altIdx !== null && (
        <div className="reply-modal-backdrop active" onClick={() => setAltIdx(null)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 400 }}>
            <button className="reply-modal-close" onClick={() => setAltIdx(null)}>×</button>
            <h3>미디어 설명</h3>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>시각 장애인을 위한 미디어 설명을 입력해주세요. 화면 낭독기에 전달됩니다.</p>
            <textarea
              value={items[altIdx]?.alt || ""}
              onChange={(e) => setItems(prev => prev.map((item, j) => j === altIdx ? { ...item, alt: e.target.value } : item))}
              placeholder="예: 푸른 하늘 아래 펼쳐진 녹색 언덕 위에 서있는 사람"
              style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button onClick={() => setAltIdx(null)} className="btn btn-primary">확인</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
