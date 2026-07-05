"use client";
import { useState, useRef } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import Icon from "./Icon";
import TextareaHighlight from "./TextareaHighlight";

const MAX_LENGTH = 500;

const VIS_OPTIONS = [
  { value: "public", label: "공개", icon: "globe" },
  { value: "home", label: "홈", icon: "home" },
  { value: "followers", label: "팔로워", icon: "lock" },
  { value: "mention", label: "멘션", icon: "mail" },
];

export default function PostForm({ parentId, onDone, placeholder, initialContent }: { parentId?: number; onDone?: () => void; placeholder?: string; initialContent?: string }) {
  const [content, setContent] = useState(initialContent || "");
  const [summary, setSummary] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [submitting, setSubmitting] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const totalLen = content.length + summary.length;
  const nearLimit = totalLen > MAX_LENGTH - 50 && totalLen <= MAX_LENGTH;
  const overLimit = totalLen > MAX_LENGTH;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (overLimit) {
      wrapRef.current?.classList.remove("shake");
      void wrapRef.current?.offsetWidth;
      wrapRef.current?.classList.add("shake");
      const btn = formRef.current?.querySelector('button[type="submit"]');
      btn?.classList.add("over-limit-submit");
      return;
    }
    if (!content.trim() || submitting) return;
    setSubmitting(true);
    try {
      await api.createPost({ content, summary, visibility, parent_id: parentId });
      setContent(""); setSummary("");
      if (onDone) onDone();
      else router.refresh();
    } catch (err: any) { alert(err.message); }
    setSubmitting(false);
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={overLimit ? "over-limit" : nearLimit ? "near-limit" : ""}>
      <div ref={wrapRef}>
        <TextareaHighlight
          value={content}
          onChange={(v) => setContent(v)}
          placeholder={placeholder || "무슨 생각을 하고 계신가요?"}
          maxLength={MAX_LENGTH}
          cwLength={summary.length}
          rows={3}
          required
          onKeyDown={(e: any) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); } }}
        />
      </div>
      <input
        type="text"
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        placeholder="CW (선택사항)"
        className="cw-input"
        onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); } }}
      />
      <div className="reply-form-footer">
        <div className="visibility-selector">
          {VIS_OPTIONS.map((v) => (
            <label key={v.value}>
              <input type="radio" name="visibility" value={v.value} checked={visibility === v.value} onChange={() => setVisibility(v.value)} />
              <Icon name={v.icon} /> {v.label}
            </label>
          ))}
        </div>
        <div className="form-footer-right">
          <span className="char-count char-count-inline">{totalLen}/{MAX_LENGTH}</span>
          <button type="submit" disabled={submitting || !content.trim()} className="btn btn-primary">
            {submitting ? "..." : parentId ? "답글" : "게시"}
          </button>
        </div>
      </div>
    </form>
  );
}
