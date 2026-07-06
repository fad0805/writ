"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { api, User } from "@/lib/api";
import { useRouter } from "next/navigation";
import TextareaHighlight from "./TextareaHighlight";
import EmojiPicker from "./EmojiPicker";
import VisibilitySelector from "./VisibilitySelector";
import { getCustomEmojis, CustomEmoji } from "@/lib/emojis";
import { useAuth } from "@/lib/auth";

const MAX_LENGTH = 500;

export default function PostForm({ parentId, onDone, placeholder, initialContent, initialVisibility, shareUrl }: { parentId?: number; onDone?: () => void; placeholder?: string; initialContent?: string; initialVisibility?: string; shareUrl?: string }) {
  const [content, setContent] = useState(initialContent || "");
  const [summary, setSummary] = useState("");
  const { user: authUser } = useAuth();
  const [visibilityOverride, setVisibilityOverride] = useState<string | null>(
    initialVisibility || null
  );
  const visibility = visibilityOverride ?? authUser?.default_visibility ?? "public";
  const [submitting, setSubmitting] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const router = useRouter();

  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionUsers, setMentionUsers] = useState<User[]>([]);
  const [mentionIdx, setMentionIdx] = useState(0);
  const [mentionStart, setMentionStart] = useState(-1);
  const mentionRef = useRef<HTMLDivElement>(null);
  const [emojiQuery, setEmojiQuery] = useState("");
  const [emojiResults, setEmojiResults] = useState<CustomEmoji[]>([]);
  const [emojiStart, setEmojiStart] = useState(-1);
  const [emojiIdx, setEmojiIdx] = useState(0);

  const totalLen = content.length + summary.length;
  const nearLimit = totalLen > MAX_LENGTH - 50 && totalLen <= MAX_LENGTH;
  const overLimit = totalLen > MAX_LENGTH;

  const detectEmoji = useCallback((val: string, cursor: number) => {
    const before = val.slice(0, cursor);
    const colonIdx = before.lastIndexOf(":");
    if (colonIdx === -1 || (colonIdx > 0 && !/[\s:]/.test(val[colonIdx - 1]))) {
      setEmojiStart(-1); setEmojiQuery(""); setEmojiResults([]);
      return;
    }
    const partial = before.slice(colonIdx + 1);
    if (partial.length === 0 || /[\s:]/.test(partial)) {
      setEmojiStart(-1); setEmojiQuery(""); setEmojiResults([]);
      return;
    }
    setEmojiStart(colonIdx);
    setEmojiQuery(partial);
  }, []);

  const detectMention = useCallback((val: string, cursor: number) => {
    const before = val.slice(0, cursor);
    const atIdx = before.lastIndexOf("@");
    if (atIdx === -1 || (atIdx > 0 && !/\s/.test(val[atIdx - 1]))) {
      setMentionStart(-1);
      setMentionQuery("");
      setMentionUsers([]);
      return;
    }
    const partial = before.slice(atIdx + 1);
    if (partial.length === 0 || /[\s@]/.test(partial)) {
      setMentionStart(-1);
      setMentionQuery("");
      setMentionUsers([]);
      return;
    }
    setMentionStart(atIdx);
    setMentionQuery(partial);
  }, []);

  useEffect(() => {
    if (!mentionQuery) return;
    const t = setTimeout(async () => {
      try {
        const res = await api.autocomplete(mentionQuery);
        setMentionUsers(res.users);
        setMentionIdx(0);
      } catch { setMentionUsers([]); }
    }, 100);
    return () => clearTimeout(t);
  }, [mentionQuery]);

  useEffect(() => {
    if (!emojiQuery) { setEmojiResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const all = await getCustomEmojis();
        const q = emojiQuery.toLowerCase();
        const matched = all.filter(e => e.keyword.startsWith(q) || (e.aliases || []).some(a => a.startsWith(q)));
        setEmojiResults(matched);
        setEmojiIdx(0);
      } catch { setEmojiResults([]); }
    }, 100);
    return () => clearTimeout(t);
  }, [emojiQuery]);

  const insertEmoji = useCallback((emo: CustomEmoji) => {
    if (emojiStart === -1) return;
    const afterEmoji = content.slice(emojiStart + 1);
    const wordEndMatch = afterEmoji.search(/[\s:]|$/);
    const wordEnd = emojiStart + 1 + (wordEndMatch >= 0 ? wordEndMatch : afterEmoji.length);
    const before = content.slice(0, emojiStart);
    const after = content.slice(wordEnd);
    const inserted = `${before}:${emo.keyword}: ${after}`;
    setContent(inserted);
    setEmojiStart(-1); setEmojiQuery(""); setEmojiResults([]);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        const pos = before.length + emo.keyword.length + 3;
        ta.setSelectionRange(pos, pos);
        ta.focus();
      }
    });
  }, [content, emojiStart]);

  const insertMention = useCallback((u: User) => {
    if (mentionStart === -1) return;
    const afterMention = content.slice(mentionStart + 1);
    const wordEndMatch = afterMention.search(/[\s@]|$/);
    const wordEnd = mentionStart + 1 + (wordEndMatch >= 0 ? wordEndMatch : afterMention.length);
    const before = content.slice(0, mentionStart);
    const after = content.slice(wordEnd);
    const inserted = `${before}@${u.username} ${after}`;
    setContent(inserted);
    setMentionStart(-1);
    setMentionQuery("");
    setMentionUsers([]);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        const pos = before.length + u.username.length + 2;
        ta.setSelectionRange(pos, pos);
        ta.focus();
      }
    });
  }, [content, mentionStart, mentionQuery]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      formRef.current?.requestSubmit();
      return;
    }
    if (emojiResults.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setEmojiIdx((i) => Math.min(i + 1, emojiResults.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setEmojiIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (emojiResults[emojiIdx]) insertEmoji(emojiResults[emojiIdx]);
      } else if (e.key === "Escape") {
        setEmojiResults([]);
      }
      return;
    }
    if (mentionUsers.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIdx((i) => Math.min(i + 1, mentionUsers.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (mentionUsers[mentionIdx]) insertMention(mentionUsers[mentionIdx]);
      } else if (e.key === "Escape") {
        setMentionUsers([]);
      }
    }
  };

  const handleContentChange = (val: string) => {
    setContent(val);
  };

  const handleTaRef = useCallback((ta: HTMLTextAreaElement | null) => {
    taRef.current = ta;
    if (ta) {
      const handler = () => {
        if (ta === document.activeElement) {
          detectMention(ta.value, ta.selectionStart);
          detectEmoji(ta.value, ta.selectionStart);
        }
      };
      ta.addEventListener("input", handler);
      ta.addEventListener("click", handler);
      ta.addEventListener("keyup", handler);
    }
  }, [detectMention]);

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
      await api.createPost({ content, summary, visibility, parent_id: parentId, share_url: shareUrl });
      setContent(""); setSummary("");
      if (onDone) onDone();
      else router.refresh();
    } catch (err: unknown) { alert(err instanceof Error ? err.message : "오류가 발생했습니다"); }
    setSubmitting(false);
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={`relative ${overLimit ? "over-limit" : nearLimit ? "near-limit" : ""}`}>
      <div ref={wrapRef}>
        <TextareaHighlight
          value={content}
          onChange={handleContentChange}
          placeholder={placeholder || "무얼 쓰고 계신가요?"}
          maxLength={MAX_LENGTH}
          cwLength={summary.length}
          rows={3}
          required
          onKeyDown={handleKeyDown}
          textareaRef={handleTaRef}
        />
      </div>
      {mentionUsers.length > 0 && (
        <div ref={mentionRef} className="mention-dropdown">
          {mentionUsers.map((u, i) => (
            <div
              key={u.id}
              className={`mention-option ${i === mentionIdx ? "active" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); insertMention(u); }}
              onMouseEnter={() => setMentionIdx(i)}
            >
              {u.avatar ? (
                <img src={u.avatar} alt="" className="mention-option-avatar object-cover" />
              ) : (
                <div className="mention-option-avatar" style={{ backgroundColor: `hsl(${hashCode(u.username) % 360}, 55%, 50%)` }}>
                  {(u.display_name || u.username)[0]}
                </div>
              )}
              <div className="mention-option-info">
                <strong>{u.display_name}</strong>
                <span>@{u.username}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {emojiResults.length > 0 && (
        <div className="mention-dropdown" style={{ border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg-secondary)", padding: 4, maxHeight: 200, overflowY: "auto", position: "absolute", zIndex: 1100, width: 260 }}>
          {emojiResults.map((emo, i) => (
            <div key={emo.id} className={`mention-option ${i === emojiIdx ? "active" : ""}`} onMouseDown={(e) => { e.preventDefault(); insertEmoji(emo); }} onMouseEnter={() => setEmojiIdx(i)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", cursor: "pointer" }}>
              <img src={emo.url} alt={emo.keyword} style={{ width: 24, height: 24, borderRadius: 4, objectFit: "contain" }} />
              <span style={{ fontSize: "0.85em" }}>:<strong>{emo.keyword}</strong>:</span>
            </div>
          ))}
        </div>
      )}
      <input
        type="text"
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        placeholder="CW (선택사항)"
        className="cw-input"
        onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); } }}
      />
      <div className="reply-form-footer">
        <VisibilitySelector value={visibility} onChange={(v) => setVisibilityOverride(v)} includeMention />
        <div className="form-footer-right">
          <EmojiPicker onEmoji={(e) => setContent(content + e)} />
          <span className="char-count char-count-inline">{totalLen}/{MAX_LENGTH}</span>
          <button type="submit" disabled={submitting || !content.trim()} className="btn btn-primary">
            {submitting ? "..." : parentId ? "답글" : "게시"}
          </button>
        </div>
      </div>
    </form>
  );
}

function hashCode(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h) + s.charCodeAt(i);
  return Math.abs(h);
}
