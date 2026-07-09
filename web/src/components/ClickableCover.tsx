"use client";
import { useState } from "react";

export default function ClickableCover({ src, isSensitive, className }: { src: string; isSensitive?: boolean; className?: string }) {
  const [revealed, setRevealed] = useState(false);
  if (!isSensitive) {
    return <img src={src} alt="" className={className} />;
  }
  const handleReveal = (e: React.MouseEvent) => { e.stopPropagation(); if (!revealed) setRevealed(true); };
  const handleHide = (e: React.MouseEvent) => { e.stopPropagation(); setRevealed(false); };
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <img src={src} alt="" className={className} style={{ filter: revealed ? "none" : "blur(12px)", transition: "filter 0.2s", cursor: isSensitive ? "pointer" : undefined }} onClick={handleReveal} />
      {!revealed && <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }} onClick={handleReveal}><span style={{ background: "rgba(0,0,0,0.6)", color: "#fff", fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 4 }}>표시</span></div>}
      {revealed && <button onClick={handleHide} style={{ position: "absolute", top: 2, right: 2, zIndex: 2, background: "rgba(0,0,0,0.6)", border: "none", borderRadius: 3, color: "#fff", fontSize: 10, padding: "2px 7px", cursor: "pointer" }}>가리기</button>}
    </div>
  );
}
