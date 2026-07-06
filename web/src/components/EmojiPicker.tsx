"use client";
import { useState, useRef, useEffect } from "react";
import Icon from "./Icon";
import { getCustomEmojis, CustomEmoji } from "@/lib/emojis";

const CATEGORIES: { name: string; emojis: string[] }[] = [
  { name: "표정", emojis: ["😀","😃","😄","😁","😅","😂","🤣","😊","😇","🙂","😉","😌","😍","🥰","😘","😗","😋","😛","😜","🤪","😝","🤑","🤗","🤭","🤫","🤔","🤐","🤨","😐","😑","😶","😏","😒","🙄","😬","🤥","😌","😔","😪","🤤","😴","😷","🤒","🤕","🤢","🤮","🥴","😵","🤯","🤠","🥳","🥸","😎","🤓","🧐","😕","😟","🙁","😮","😯","😲","😳","🥺","😦","😧","😨","😰","😥","😢","😭","😱","😖","😣","😞","😓","😩","😫","🥱","😤","😡","😠","🤬"] },
  { name: "손동작", emojis: ["👋","🤚","🖐","✋","🖖","👌","🤏","✌","🤞","🤟","🤘","🤙","👈","👉","👆","🖕","👇","👍","👎","✊","👊","🤛","🤜","👏","🙌","👐","🤲","🤝","🙏","✍","💅"] },
  { name: "사람", emojis: ["👂","👃","👣","👀","🗣","👤","👥","💪","🦵","🦶","👑","👒","🎩","🎓","🧢","👟","👞","👡","👠","👢","👕","👔","👗","👘","👙","👚","👛","👜","👝","🎒","💼","👓","🕶","💍"] },
  { name: "하트", emojis: ["❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","💔","❣️","💕","💞","💓","💗","💖","💘","💝"] },
  { name: "기타", emojis: ["💯","💠","🌈","⭐","🌟","✨","⚡","🔥","💥","💦","💨","☄️","🌊","🍕","🍔","🍟","🌭","🍿","🧁","🍩","🍪","🍫","🍬","🍭","🍮","🍯","🍰","🎂","🍨","🍧","🍦"] },
];

export default function EmojiPicker({ onEmoji, dropUp }: { onEmoji: (emoji: string) => void; dropUp?: boolean }) {
  const [open, setOpen] = useState(false);
  const [customEmojis, setCustomEmojis] = useState<CustomEmoji[]>([]);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) getCustomEmojis().then(setCustomEmojis);
  }, [open]);

  const localEmojis = customEmojis.filter(e => e.category !== "remote");
  const groupedCustom = localEmojis.reduce<Record<string, CustomEmoji[]>>((acc, e) => {
    const cat = e.category || "기타";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(e);
    return acc;
  }, {});

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
      <button type="button" onClick={() => setOpen(!open)} className="emoji-trigger">
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
            <div key={ci} className="emoji-custom-row" style={{ background: ci % 2 === 0 ? "transparent" : "rgba(128,128,128,0.08)" }}>
              <div className="emoji-row-label">{cat.name}</div>
              <div className="emoji-row-grid">
                {cat.emojis.map((e, i) => (
                  <button key={i} type="button" onClick={() => { onEmoji(e); setOpen(false); }} className="emoji-cell" style={{ fontSize: "1.3em" }}>
                    {e}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {customEmojis.length > 0 && Object.entries(groupedCustom).map(([catName, emos]) => (
            <div key={`c-${catName}`} className="emoji-custom-row">
              <div className="emoji-row-label">{catName}</div>
              <div className="emoji-row-grid">
                {emos.map((emo) => (
                  <button key={emo.id} type="button" onClick={() => { onEmoji(`:${emo.keyword}:`); setOpen(false); }} className="emoji-cell emoji-cell-large">
                    <img src={emo.url} alt={emo.keyword} width={33} height={33} className="emoji-img" />
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
