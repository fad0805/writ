"use client";
import { useState, useRef, useEffect, useCallback, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";
import { getCustomEmojis, CustomEmoji } from "@/lib/emojis";
import { getFrequentEmojis } from "@/lib/emoji-usage";

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
  const [frequent, setFrequent] = useState<string[]>([]);
  const pickerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.dispatchEvent(new CustomEvent("writ:emoji-picker", { detail: { open } }));
  }, [open]);

  useEffect(() => {
    if (open) {
      setSearch("");
      setFrequent(getFrequentEmojis(14));
    }
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

  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const lastHeightRef = useRef(0);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [flipUp, setFlipUp] = useState(false);

  const updatePos = useCallback(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const h = dropdownRef.current ? dropdownRef.current.getBoundingClientRect().height : 0;
    const estH = h > 0 ? h : 420;
    const flip = dropUp || r.bottom + estH + 8 > window.innerHeight;
    setFlipUp(flip);
    setPos({
      top: flip ? r.top - 4 : r.bottom + 4,
      left: r.left + r.width / 2,
    });
  }, [dropUp]);

  useEffect(() => {
    if (!open) { setPos(null); setFlipUp(false); return; }
    updatePos();
    window.addEventListener("scroll", updatePos, true);
    window.addEventListener("resize", updatePos);
    return () => { window.removeEventListener("scroll", updatePos, true); window.removeEventListener("resize", updatePos); };
  }, [open, updatePos]);

  useLayoutEffect(() => {
    if (!open || !dropdownRef.current) return;
    const h = dropdownRef.current.getBoundingClientRect().height;
    if (h !== lastHeightRef.current) {
      lastHeightRef.current = h;
      updatePos();
    }
  }, [open, updatePos, customEmojis, search]);

  return (
    <div ref={pickerRef} className="relative-wrap">
      <button ref={triggerRef} type="button" onClick={() => setOpen(!open)} className="emoji-trigger">
        <Icon name="smile" size={18} />
      </button>
      {open && pos && createPortal(
        <div ref={dropdownRef} className="emoji-picker-dropdown" style={{
          position: "fixed",
          top: pos.top,
          left: pos.left,
          transform: (dropUp || flipUp) ? "translate(-50%, -100%)" : "translateX(-50%)",
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
          {!search && frequent.length > 0 && (
            <div className="emoji-custom-row">
              <div className="emoji-row-label">자주 쓰는 에모지</div>
              <div className="emoji-row-grid">
                {frequent.filter(e => {
                    if (!e.startsWith(":")) return true;
                    const kw = e.slice(1, -1);
                    return customEmojis.some(c => c.keyword === kw);
                  }).map((emoji) => {
                  const isCustom = emoji.startsWith(":") && emoji.endsWith(":");
                  const kw = isCustom ? emoji.slice(1, -1) : emoji;
                  const matched = isCustom ? customEmojis.find(e => e.keyword === kw) : null;
                  return (
                    <button key={emoji} type="button" onClick={() => { onEmoji(emoji); setOpen(false); }} className="emoji-cell emoji-cell-large">
                      {matched ? (
                        <img src={matched.url} alt={kw} width={33} height={33} className="emoji-img" />
                      ) : (
                        <span style={{ fontSize: 28 }}>{emoji}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {customEmojis.length > 0 && Object.entries(groupedCustom).sort(([a], [b]) => a.localeCompare(b, 'ko')).map(([catName, emos]) => (
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
        </div>,
        document.body
      )}
    </div>
  );
}
