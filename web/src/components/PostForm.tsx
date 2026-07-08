"use client";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { api, User } from "@/lib/api";
import Icon from "@/components/Icon";
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
  const [mentionPos, setMentionPos] = useState({ top: 0, left: 0 });
  const mentionRef = useRef<HTMLDivElement>(null);
  const [emojiQuery, setEmojiQuery] = useState("");
  const [emojiResults, setEmojiResults] = useState<CustomEmoji[]>([]);
  const [emojiStart, setEmojiStart] = useState(-1);
  const [emojiIdx, setEmojiIdx] = useState(0);
  const [emojiPos, setEmojiPos] = useState({ top: 0, left: 0 });
  const [hashtagStart, setHashtagStart] = useState(-1);
  const [hashtagQuery, setHashtagQuery] = useState("");
  const [hashtagResults, setHashtagResults] = useState<string[]>([]);
  const [hashtagIdx, setHashtagIdx] = useState(0);
  const [hashtagPos, setHashtagPos] = useState({ top: 0, left: 0 });
  const [seriesResults, setSeriesResults] = useState<{ id: number; title: string; cover_image: string }[]>([]);
  const [seriesIdx, setSeriesIdx] = useState(0);
  const [seriesPos, setSeriesPos] = useState({ top: 0, left: 0 });
  const [showSeriesSearch, setShowSeriesSearch] = useState(false);
  const [seriesSearchQ, setSeriesSearchQ] = useState("");
  const seriesSearchRef = useRef<HTMLInputElement>(null);

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
    // Position near cursor in textarea
    const ta = taRef.current;
    if (ta) {
      const rect = ta.getBoundingClientRect();
      const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
      const textBefore = val.slice(0, cursor);
      const lines = textBefore.split('\n');
      const top = rect.top + lines.length * lineHeight + 4;
      const lastLine = lines[lines.length - 1] || '';
      const left = rect.left + lastLine.length * 8 + 10;
      setEmojiPos({ top, left });
    }
  }, []);

  const detectMention = useCallback((val: string, cursor: number) => {
    const before = val.slice(0, cursor);
    const atIdx = before.lastIndexOf("@");
    if (atIdx === -1 || (atIdx > 0 && !/\s/.test(val[atIdx - 1]))) {
      setMentionStart(-1); setMentionQuery(""); setMentionUsers([]);
      return;
    }
    const partial = before.slice(atIdx + 1);
    if (partial.length === 0 || /[\s@]/.test(partial)) {
      setMentionStart(-1); setMentionQuery(""); setMentionUsers([]);
      return;
    }
    setMentionStart(atIdx);
    setMentionQuery(partial);
    const ta = taRef.current;
    if (ta) {
      const rect = ta.getBoundingClientRect();
      const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
      const textBefore = val.slice(0, cursor);
      const lines = textBefore.split('\n');
      const top = rect.top + lines.length * lineHeight + 4;
      const lastLine = lines[lines.length - 1] || '';
      const left = rect.left + lastLine.length * 8 + 10;
      setMentionPos({ top, left });
    }
  }, []);

  useEffect(() => {
    if (!mentionQuery) { setMentionUsers([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await api.autocomplete(mentionQuery);
        setMentionUsers(res.users);
        setMentionIdx(0);
      } catch { setMentionUsers([]); }
    }, 100);
    return () => clearTimeout(t);
  }, [mentionQuery]);

  const detectHashtag = useCallback((val: string, cursor: number) => {
    const before = val.slice(0, cursor);
    const hashIdx = before.lastIndexOf("#");
    if (hashIdx === -1 || (hashIdx > 0 && !/\s/.test(val[hashIdx - 1]))) {
      setHashtagStart(-1); setHashtagQuery(""); setHashtagResults([]);
      return;
    }
    const partial = before.slice(hashIdx + 1);
    if (/[\s#]/.test(partial) || partial.length === 0) {
      setHashtagStart(-1); setHashtagQuery(""); setHashtagResults([]);
      return;
    }
    setHashtagStart(hashIdx);
    setHashtagQuery(partial);
    const ta = taRef.current;
    if (ta) {
      const rect = ta.getBoundingClientRect();
      const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
      const textBefore = val.slice(0, cursor);
      const lines = textBefore.split('\n');
      const top = rect.top + lines.length * lineHeight + 4;
      const lastLine = lines[lines.length - 1] || '';
      const left = rect.left + lastLine.length * 8 + 10;
      setHashtagPos({ top, left });
    }
  }, []);

  useEffect(() => {
    if (!hashtagQuery) { setHashtagResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/tags?q=${encodeURIComponent(hashtagQuery)}`, { credentials: "include" });
        if (res.ok) { const d = await res.json(); setHashtagResults(d.tags?.map((t: any) => t.name) || []); setHashtagIdx(0); }
        else setHashtagResults([]);
      } catch { setHashtagResults([]); }
    }, 100);
    return () => clearTimeout(t);
  }, [hashtagQuery]);

  const detectSeries = useCallback((val: string, cursor: number) => {
    const before = val.slice(0, cursor);
    const slashIdx = before.lastIndexOf("/");
    if (slashIdx === -1 || (slashIdx > 0 && !/\s/.test(val[slashIdx - 1]))) {
      setShowSeriesSearch(false); setSeriesResults([]); return;
    }
    const raw = before.slice(slashIdx + 1);
    const cmd = raw.toLowerCase();
    if (cmd !== "series" && cmd !== "시리즈" && !cmd.startsWith("series ") && !cmd.startsWith("시리즈 ")) {
      setShowSeriesSearch(false); setSeriesResults([]); return;
    }
    if (!cmd.includes(" ") && (cmd === "series" || cmd === "시리즈")) {
      setShowSeriesSearch(true); setSeriesSearchQ(""); setSeriesResults([]);
      const ta = taRef.current;
      if (ta) {
        const rect = ta.getBoundingClientRect();
        const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
        const textBefore = val.slice(0, cursor);
        const lines = textBefore.split('\n');
        const top = rect.top + lines.length * lineHeight + 4;
        const lastLine = lines[lines.length - 1] || '';
        const left = rect.left + lastLine.length * 8 + 10;
        setSeriesPos({ top, left });
      }
      setTimeout(() => seriesSearchRef.current?.focus(), 0);
      return;
    }
    setShowSeriesSearch(false); setSeriesResults([]);
  }, []);

  useEffect(() => {
    if (!showSeriesSearch) return;
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/series?q=${encodeURIComponent(seriesSearchQ)}`, { credentials: "include" });
        if (res.ok) { const d = await res.json(); setSeriesResults(d.series?.map((s: any) => ({ id: s.id, title: s.title, cover_image: s.cover_image })) || []); setSeriesIdx(0); }
        else setSeriesResults([]);
      } catch { setSeriesResults([]); }
    }, 100);
    return () => clearTimeout(t);
  }, [seriesSearchQ, showSeriesSearch]);

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

  // Close emoji picker on scroll/resize/click-outside/Escape
  useEffect(() => {
    if (!emojiQuery) return;
    const close = () => setEmojiResults([]);
    const keyHandler = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    document.addEventListener("keydown", keyHandler);
    const clickHandler = (e: MouseEvent) => {
      const popup = document.querySelector('.emoji-autocomplete');
      if (popup && !popup.contains(e.target as Node)) close();
    };
    setTimeout(() => document.addEventListener("click", clickHandler), 0);
    return () => {
      document.removeEventListener("keydown", keyHandler);
      document.removeEventListener("click", clickHandler);
    };
  }, [emojiQuery]);

  // Close series search on click-outside/Escape
  useEffect(() => {
    if (!showSeriesSearch) return;
    const close = () => { setShowSeriesSearch(false); setSeriesResults([]); };
    const keyHandler = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", keyHandler);
    const clickHandler = (e: MouseEvent) => {
      const popup = document.querySelector('.emoji-autocomplete');
      if (popup && !popup.contains(e.target as Node)) close();
    };
    setTimeout(() => document.addEventListener("click", clickHandler), 0);
    return () => {
      document.removeEventListener("keydown", keyHandler);
      document.removeEventListener("click", clickHandler);
    };
  }, [showSeriesSearch]);

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
  }, [content, mentionStart]);

  const insertHashtag = useCallback((tag: string) => {
    if (hashtagStart === -1) return;
    const afterHash = content.slice(hashtagStart + 1);
    const wordEndMatch = afterHash.search(/[\s#]|$/);
    const wordEnd = hashtagStart + 1 + (wordEndMatch >= 0 ? wordEndMatch : afterHash.length);
    const before = content.slice(0, hashtagStart);
    const after = content.slice(wordEnd);
    const inserted = `${before}#${tag} ${after}`;
    setContent(inserted);
    setHashtagStart(-1); setHashtagQuery(""); setHashtagResults([]);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        const pos = before.length + tag.length + 2;
        ta.setSelectionRange(pos, pos);
        ta.focus();
      }
    });
  }, [content, hashtagStart]);

  const insertSeries = useCallback((novel: { id: number; title: string }) => {
    const slashIdx = content.lastIndexOf("/");
    const before = slashIdx > 0 ? content.slice(0, slashIdx - 1) : "";
    const fullUrl = `${window.location.origin}/series/${novel.id}`;
    const inserted = `${before} ${fullUrl} `;
    setContent(inserted);
    setShowSeriesSearch(false); setSeriesResults([]); setSeriesSearchQ("");
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        ta.setSelectionRange(inserted.length, inserted.length);
        ta.focus();
      }
    });
  }, [content]);

  const handleTaEvent = useCallback((e: React.KeyboardEvent | React.MouseEvent) => {
    const el = e.target as HTMLTextAreaElement;
    detectMention(el.value, el.selectionStart);
    detectEmoji(el.value, el.selectionStart);
    detectHashtag(el.value, el.selectionStart);
    detectSeries(el.value, el.selectionStart);
  }, [detectMention]);

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
      return;
    }
    if (hashtagResults.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHashtagIdx((i) => Math.min(i + 1, hashtagResults.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHashtagIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (hashtagResults[hashtagIdx]) insertHashtag(hashtagResults[hashtagIdx]);
      } else if (e.key === "Escape") {
        setHashtagResults([]);
      }
      return;
    }
    if (seriesResults.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSeriesIdx((i) => Math.min(i + 1, seriesResults.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSeriesIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (seriesResults[seriesIdx]) insertSeries(seriesResults[seriesIdx]);
      } else if (e.key === "Escape") {
        setShowSeriesSearch(false); setSeriesResults([]);
      }
    }
  };

  const handleContentChange = (val: string, cursor?: number) => {
    setContent(val);
    const pos = cursor ?? (taRef.current?.selectionStart ?? val.length);
    detectMention(val, pos);
    detectEmoji(val, pos);
    detectHashtag(val, pos);
    detectSeries(val, pos);
  };

  const handleTaRef = useCallback((ta: HTMLTextAreaElement | null) => {
    taRef.current = ta;
  }, []);

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
          onKeyUp={handleTaEvent}
          onMouseUp={handleTaEvent}
          textareaRef={handleTaRef}
        />
      </div>
      {mentionUsers.length > 0 && (
        <div className="emoji-autocomplete mention-dropdown-pos" style={{ top: mentionPos.top, left: mentionPos.left }}>
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
      {showSeriesSearch && (
        <div className="emoji-autocomplete" style={{ top: seriesPos.top, left: seriesPos.left, padding: 8 }}>
          <input ref={seriesSearchRef} type="text" value={seriesSearchQ} onChange={e => setSeriesSearchQ(e.target.value)} placeholder="시리즈 검색..." className="cw-input" style={{ width: "100%", marginBottom: seriesResults.length > 0 ? 6 : 0, fontSize: "0.85em" }} />
          {seriesResults.length > 0 && (
            <div style={{ maxHeight: 180, overflowY: "auto" }}>
              {seriesResults.map((s, i) => (
                <div key={s.id} className={`mention-option ${i === seriesIdx ? "active" : ""}`} onMouseDown={(e) => { e.preventDefault(); insertSeries(s); }} onMouseEnter={() => setSeriesIdx(i)} style={{ padding: "4px 8px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {s.cover_image ? <img src={s.cover_image} alt="" style={{ width: 24, height: 24, borderRadius: 4, objectFit: "cover" }} /> : <div style={{ width: 24, height: 24, borderRadius: 4, background: "var(--bg-secondary)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.7em" }}><Icon name="book" size={12} /></div>}
                    <span style={{ fontSize: "0.9em" }}>{s.title}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
          {!seriesSearchQ && seriesResults.length === 0 && <div style={{ fontSize: "0.85em", color: "var(--text-muted)", padding: "4px 0" }}>시리즈를 검색하세요.</div>}
        </div>
      )}
      {emojiResults.length > 0 && (
        <div className="emoji-autocomplete" style={{
          top: emojiPos.top,
          left: emojiPos.left,
        }}>
          <div className="emoji-autocomplete-grid">
            {emojiResults.map((emo, i) => (
              <div key={emo.id} className={`mention-option ${i === emojiIdx ? "active" : ""} emoji-autocomplete-item`} onMouseDown={(e) => { e.preventDefault(); insertEmoji(emo); }} onMouseEnter={() => setEmojiIdx(i)}>
                <img src={emo.url} alt={emo.keyword} className="emoji-autocomplete-img" />
                <span className="emoji-autocomplete-label">:<strong>{emo.keyword}</strong>:</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {hashtagResults.length > 0 && (
        <div className="emoji-autocomplete" style={{ top: hashtagPos.top, left: hashtagPos.left }}>
          {hashtagResults.map((tag, i) => (
            <div key={tag} className={`mention-option ${i === hashtagIdx ? "active" : ""}`} onMouseDown={(e) => { e.preventDefault(); insertHashtag(tag); }} onMouseEnter={() => setHashtagIdx(i)} style={{ padding: "6px 12px" }}>
              <span style={{ fontSize: "0.9em" }}>#{tag}</span>
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
