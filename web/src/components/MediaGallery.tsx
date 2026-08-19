"use client";
import AudioPlayer from "./AudioPlayer";
export type MediaItem = { url: string; type: string; alt?: string };

export default function MediaGallery({ media, sensitive, revealed, onReveal, onHide, onOpen }: {
  media: MediaItem[];
  sensitive: boolean;
  revealed: boolean;
  onReveal: () => void;
  onHide: () => void;
  onOpen: (index: number) => void;
}) {
  const n = media.length;
  const single = n === 1;

  // 이미지 수에 따른 동적 그리드 계산
  const getGridConfig = (count: number) => {
    if (count === 1) return { columns: 1, rows: 1, aspectRatio: "16/9" };
    if (count === 2) return { columns: 2, rows: 1, aspectRatio: "1/1" };
    if (count <= 4) return { columns: 2, rows: 2, aspectRatio: "1/1" };
    if (count <= 6) return { columns: 3, rows: 2, aspectRatio: "1/1" };
    if (count <= 9) return { columns: 3, rows: 3, aspectRatio: "1/1" };
    if (count <= 12) return { columns: 4, rows: 3, aspectRatio: "1/1" };
    return { columns: 4, rows: 4, aspectRatio: "1/1" };
  };

  const gridConfig = getGridConfig(n);

  return (
    <div style={{ position: "relative", marginTop: 8, overflow: "hidden", borderRadius: 8 }}>
      {single ? (
        <div className="post-media-single">
          {media.slice(0, 1).map((m: MediaItem, i: number) => {
            const blurred = sensitive && !revealed;
            return m.type === "video" ? (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", borderRadius: 6 }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 6, zIndex: 1 }} />}
                <video src={m.url} controls style={{ width: "100%", maxHeight: 400, borderRadius: 6, objectFit: "contain", background: "#000", filter: blurred ? "blur(20px)" : "none" }} />
              </div>
            ) : m.type === "audio" ? (
              <div key={i} style={{ position: "relative", padding: "12px 8px", background: "#1a1a2e", borderRadius: 6 }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 6, zIndex: 1 }} />}
                <AudioPlayer src={m.url} />
              </div>
            ) : (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", borderRadius: 6 }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 6, zIndex: 1 }} />}
                <img src={m.url} alt={m.alt || ""} style={{ width: "100%", maxHeight: 400, borderRadius: 6, objectFit: "contain", background: "#000", cursor: blurred ? "default" : "pointer", filter: blurred ? "blur(20px)" : "none" }} onClick={(e) => { if (!blurred) { e.stopPropagation(); onOpen(i); } }} />
              </div>
            );
          })}
        </div>
      ) : (
        <div 
          className="post-media-grid" 
          style={{ 
            display: "grid", 
            gridTemplateColumns: `repeat(${gridConfig.columns}, 1fr)`, 
            gridAutoRows: "1fr",
            gap: 0 
          }}
        >
          {media.slice(0, 16).map((m: MediaItem, i: number) => {
            const blurred = sensitive && !revealed;
            return m.type === "video" ? (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", aspectRatio: gridConfig.aspectRatio }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 1 }} />}
                <video src={m.url} controls style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000", filter: blurred ? "blur(20px)" : "none" }} />
              </div>
            ) : m.type === "audio" ? (
              <div key={i} style={{ position: "relative", padding: "12px 8px", background: "#1a1a2e", height: "100%", display: "flex", alignItems: "center", aspectRatio: gridConfig.aspectRatio }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 1 }} />}
                <AudioPlayer src={m.url} />
              </div>
            ) : (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", aspectRatio: gridConfig.aspectRatio }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 1 }} />}
                <img src={m.url} alt={m.alt || ""} style={{ width: "100%", height: "100%", objectFit: "cover", background: "#000", cursor: blurred ? "default" : "pointer", filter: blurred ? "blur(20px)" : "none" }} onClick={(e) => { if (!blurred) { e.stopPropagation(); onOpen(i); } }} />
              </div>
            );
          })}
        </div>
      )}
      {sensitive && !revealed && (
        <div onClick={(e) => { e.stopPropagation(); e.preventDefault(); onReveal(); }} style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2, cursor: "pointer", color: "#fff", fontSize: 13, fontWeight: 600 }}>
          <span style={{ fontSize: 12, fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>클릭하여 표시</span>
        </div>
      )}
      {sensitive && revealed && (
        <button onClick={(e) => { e.stopPropagation(); onHide(); }} style={{ position: "absolute", top: 8, right: 8, zIndex: 2, background: "rgba(0,0,0,0.6)", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, padding: "3px 10px", cursor: "pointer" }}>가리기</button>
      )}
    </div>
  );
}
