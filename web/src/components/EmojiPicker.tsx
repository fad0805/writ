"use client";
import { useState, useRef, useEffect } from "react";
import Icon from "./Icon";

const CATEGORIES: { name: string; emojis: string[] }[] = [
  { name: "표정", emojis: ["😀","😃","😄","😁","😅","😂","🤣","😊","😇","🙂","😉","😌","😍","🥰","😘","😗","😋","😛","😜","🤪","😝","🤑","🤗","🤭","🤫","🤔","🤐","🤨","😐","😑","😶","😏","😒","🙄","😬","🤥","😌","😔","😪","🤤","😴","😷","🤒","🤕","🤢","🤮","🥴","😵","🤯","🤠","🥳","🥸","😎","🤓","🧐","😕","😟","🙁","😮","😯","😲","😳","🥺","😦","😧","😨","😰","😥","😢","😭","😱","😖","😣","😞","😓","😩","😫","🥱","😤","😡","😠","🤬"] },
  { name: "손동작", emojis: ["👋","🤚","🖐","✋","🖖","👌","🤏","✌","🤞","🤟","🤘","🤙","👈","👉","👆","🖕","👇","👍","👎","✊","👊","🤛","🤜","👏","🙌","👐","🤲","🤝","🙏","✍","💅"] },
  { name: "사람", emojis: ["👂","👃","👣","👀","🗣","👤","👥","💪","🦵","🦶","👑","👒","🎩","🎓","🧢","👟","👞","👡","👠","👢","👕","👔","👗","👘","👙","👚","👛","👜","👝","🎒","💼","👓","🕶","💍"] },
  { name: "하트", emojis: ["❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","💔","❣️","💕","💞","💓","💗","💖","💘","💝"] },
  { name: "기타", emojis: ["💯","💠","🌈","⭐","🌟","✨","⚡","🔥","💥","💦","💨","☄️","🌊","🍕","🍔","🍟","🌭","🍿","🧁","🍩","🍪","🍫","🍬","🍭","🍮","🍯","🍰","🎂","🍨","🍧","🍦"] },
];

export default function EmojiPicker({ onEmoji, dropUp }: { onEmoji: (emoji: string) => void; dropUp?: boolean }) {
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setOpen(false);
    };
    setTimeout(() => document.addEventListener("click", handler), 0);
    return () => document.removeEventListener("click", handler);
  }, [open]);

  return (
    <div ref={pickerRef} style={{ position: "relative" }}>
      <button type="button" onClick={() => setOpen(!open)} style={{ background: "none", border: "none", cursor: "pointer", padding: "4px 6px", borderRadius: 4, color: "var(--accent)", display: "flex", alignItems: "center" }}>
        <Icon name="smile" size={18} />
      </button>
      {open && (
        <div style={{
          position: "absolute",
          [dropUp ? "bottom" : "top"]: "100%",
          [dropUp ? "marginBottom" : "marginTop"]: 4,
          right: 0,
          width: 300,
          height: 280,
          background: "var(--bg-secondary)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          zIndex: 1100,
          boxShadow: "0 8px 30px rgba(0,0,0,0.2)",
          overflowY: "auto",
          padding: 8,
        }}>
          {CATEGORIES.map((cat, ci) => (
            <div key={ci} style={{ background: ci % 2 === 0 ? "transparent" : "rgba(128,128,128,0.08)", borderRadius: 8, padding: "0 4px" }}>
              <div style={{ fontSize: "0.82em", color: "var(--text-primary)", padding: "10px 4px 4px", fontWeight: 700 }}>{cat.name}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 2, paddingBottom: 4 }}>
                {cat.emojis.map((e, i) => (
                  <button key={i} type="button" onClick={() => { onEmoji(e); setOpen(false); }} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1.3em", padding: 2, borderRadius: 4, width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.15s" }}>
                    {e}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
