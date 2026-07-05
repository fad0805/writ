"use client";
import { useRef, useCallback, useEffect, useState } from "react";

export default function TextareaHighlight({
  value, onChange, placeholder, maxLength, cwLength, textareaRef: externalRef, ...props
}: {
  value: string; onChange: (v: string) => void; placeholder?: string;
  maxLength: number; cwLength: number;
  rows?: number; required?: boolean;
  onKeyDown?: (e: React.KeyboardEvent) => void;
  textareaRef?: (el: HTMLTextAreaElement | null) => void;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);

  const contentLimit = Math.max(0, maxLength - cwLength);
  const before = value.slice(0, contentLimit);
  const after = value.slice(contentLimit);

  const sync = useCallback(() => {
    const ta = taRef.current;
    const pre = preRef.current;
    if (ta && pre) {
      pre.scrollTop = ta.scrollTop;
      pre.scrollLeft = ta.scrollLeft;
    }
  }, []);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.addEventListener("scroll", sync);
    return () => ta.removeEventListener("scroll", sync);
  }, [sync]);

  const setTextareaRef = useCallback((el: HTMLTextAreaElement | null) => {
    (taRef as React.MutableRefObject<HTMLTextAreaElement | null>).current = el;
    if (externalRef) externalRef(el);
  }, [externalRef]);

  return (
    <div className="textarea-wrap">
      <pre ref={preRef} className="textarea-highlight" aria-hidden="true">
        <span>{before}</span>
        {after && <mark>{after}</mark>}
      </pre>
      <textarea
        ref={setTextareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        onScroll={sync}
        className="textarea-ta"
        {...props}
      />
    </div>
  );
}
