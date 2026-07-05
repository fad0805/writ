"use client";
import { useState, useRef } from "react";

const MAX_TAGS = 10;

export default function TagInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const tags = value ? value.split(/[ ,]+/).filter(Boolean) : [];

  const [shake, setShake] = useState(false);

  const addTag = (text: string) => {
    const t = text.trim();
    if (!t) return;
    if (tags.includes(t) || tags.length >= MAX_TAGS) {
      setShake(true);
      setTimeout(() => setShake(false), 300);
      return;
    }
    onChange([...tags, t].join(" "));
    setInput("");
  };

  const removeTag = (index: number) => {
    const next = tags.filter((_, i) => i !== index);
    onChange(next.join(" "));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag(e.key === "Enter" ? input : input.slice(0, -1));
    }
    if (e.key === "Backspace" && !input && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  };

  return (
    <div className={`tag-wrapper${shake ? " shake" : ""}`} onClick={() => inputRef.current?.focus()}>
      {tags.map((t, i) => (
        <span key={i} className="tag-chip">
          {t}
          <button type="button" onClick={(e) => { e.stopPropagation(); removeTag(i); }}>×</button>
        </span>
      ))}
      {tags.length < MAX_TAGS && (
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => {
            const v = e.target.value;
            if (v.endsWith(",") || v.endsWith(" ") || v.endsWith("\n")) {
              addTag(v.slice(0, -1));
            } else {
              setInput(v);
            }
          }}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? "태그 입력" : ""}
          className="tag-text-input"
        />
      )}
    </div>
  );
}
