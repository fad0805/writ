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
  const [search, setSearch] = useState("");
  const pickerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => searchRef.current?.focus(), 50);
  }, [open]);

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
  const searchResults = search ? customEmojis.filter(e => e.category !== "remote" && (e.keyword.includes(search.toLowerCase()) || (e.aliases || []).some((a: string) => a.includes(search.toLowerCase())))) : [];

  useEffect(() => {
    if (!open) return;
    const clickHandler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const keyHandler = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    setTimeout(() => document.addEventListener("click", clickHandler), 0);
    document.addEventListener("keydown", keyHandler);
    return () => { document.removeEventListener("click", clickHandler); document.removeEventListener("keydown", keyHandler); };
  }, [open]);

  return (
    <div ref={pickerRef} className="relative-wrap">
      <button type="button" onClick={() => setOpen(!open)} className="emoji-trigger">
        <Icon name="smile" size={18} />
      </button>
      {open && (
        <div className="emoji-picker-dropdown" style={{
          [dropUp ? "bottom" : "top"]: "100%",
          [dropUp ? "marginBottom" : "marginTop"]: 4,
        }}>
          <input ref={searchRef} type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="이모지 검색..." className="cw-input emoji-picker-search" />
          {search && searchResults.length > 0 && (
            <div className="emoji-row-grid emoji-row-gap">
              {searchResults.map((emo) => (
                <button key={emo.id} type="button" onClick={() => { onEmoji(`:${emo.keyword}:`); setOpen(false); }} className="emoji-cell emoji-cell-large">
                  <img src={emo.url} alt={emo.keyword} width={33} height={33} className="emoji-img" />
                </button>
              ))}
            </div>
          )}
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
          {CATEGORIES.map((cat, ci) => (
            <div key={ci} className="emoji-custom-row" style={{ background: ci % 2 === 0 ? "transparent" : "rgba(128,128,128,0.08)" }}>
              <div className="emoji-row-label">{cat.name}</div>
              <div className="emoji-row-grid">
                {cat.emojis.map((e, i) => (
                  <button key={i} type="button" onClick={() => { onEmoji(e); setOpen(false); }} className="emoji-cell emoji-cell-lg">
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
