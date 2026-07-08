"use client";
import { useRef, useCallback } from "react";

export default function TextareaHighlight({
  value, onChange, placeholder, maxLength, cwLength, textareaRef: externalRef, ...props
}: {
  value: string; onChange: (v: string) => void; placeholder?: string;
  maxLength: number; cwLength: number;
  rows?: number; required?: boolean;
  onKeyDown?: (e: React.KeyboardEvent) => void;
  onKeyUp?: (e: React.KeyboardEvent) => void;
  onMouseUp?: (e: React.MouseEvent) => void;
  textareaRef?: (el: HTMLTextAreaElement | null) => void;
}) {
  const setTextareaRef = useCallback((el: HTMLTextAreaElement | null) => {
    if (externalRef) externalRef(el);
  }, [externalRef]);

  return (
    <div className="textarea-wrap">
      <textarea
        ref={setTextareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="textarea-ta"
        {...props}
      />
    </div>
  );
}
