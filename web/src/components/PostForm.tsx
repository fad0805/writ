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

export default function PostForm({ parentId, onDone, placeholder, initialContent, initialVisibility, shareUrl }: { parentId?: number; onDone?: (post?: any) => void; placeholder?: string; initialContent?: string; initialVisibility?: string; shareUrl?: string }) {
  const [content, setContent] = useState(initialContent || "");
  const [summary, setSummary] = useState("");
  const [postSensitive, setPostSensitive] = useState(false);
  const { user: authUser } = useAuth();
  const [visibilityOverride, setVisibilityOverride] = useState<string | null>(
    initialVisibility || null
  );
  const visibility = visibilityOverride ?? authUser?.default_visibility ?? "public";
  const visOpts = [
    { value: "public", label: "공개", icon: "globe" },
    { value: "home", label: "홈", icon: "home" },
    { value: "followers", label: "팔로워", icon: "lock" },
    { value: "mention", label: "멘션", icon: "mail" },
  ];
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
  const [mediaItems, setMediaItems] = useState<{ id: number; url: string; type: string; file?: File; alt?: string }[]>([]);
  const mediaIdRef = useRef(0);
  const [mediaUploading, setMediaUploading] = useState(false);
  const [mediaWarning, setMediaWarning] = useState("");
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const [showVisPicker, setShowVisPicker] = useState(false);
  const [showPoll, setShowPoll] = useState(false);
  const [pollOptions, setPollOptions] = useState<string[]>(["", ""]);
  const [pollExpiresIn, setPollExpiresIn] = useState(1440);
  const pollLastRef = useRef<HTMLInputElement>(null);
  const [altModalIdx, setAltModalIdx] = useState<number | null>(null);
  const [seriesResults, setSeriesResults] = useState<{ id: number; title: string; cover_image: string }[]>([]);
  const [seriesIdx, setSeriesIdx] = useState(0);
  const [seriesPos, setSeriesPos] = useState({ top: 0, left: 0 });
  const [showSeriesSearch, setShowSeriesSearch] = useState(false);
  const [seriesSearchQ, setSeriesSearchQ] = useState("");
  const seriesSearchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!showVisPicker) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as Element)?.closest?.(".vis-btn-wrap")) setShowVisPicker(false);
    };
    setTimeout(() => document.addEventListener("click", close), 0);
    return () => document.removeEventListener("click", close);
  }, [showVisPicker]);

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
        const matched = all.filter(e => e.category !== "remote" && (e.keyword.startsWith(q) || (e.aliases || []).some(a => a.startsWith(q))));
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
    const close = () => {
      const cur = taRef.current?.value || content;
      const slashIdx = cur.lastIndexOf("/");
      if (slashIdx >= 0 && (cur.slice(slashIdx + 1).toLowerCase().startsWith("series") || cur.slice(slashIdx + 1).toLowerCase().startsWith("시리즈"))) {
        const after = cur.slice(slashIdx);
        const wordEndMatch = after.search(/[\s]|$/);
        const wordEnd = slashIdx + (wordEndMatch >= 0 ? wordEndMatch : after.length);
        setContent((cur.slice(0, slashIdx - 1) + cur.slice(wordEnd)).replace(/^\s+/, ""));
      }
      setShowSeriesSearch(false); setSeriesResults([]);
    };
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
  }, [showSeriesSearch, content]);

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
    const mentionRegex = /@[a-zA-Z_][a-zA-Z0-9_]*(?:@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})?/g;
    const afterMention = content.slice(mentionStart + 1);
    const wordEndMatch = afterMention.search(mentionRegex);
    const wordEnd = mentionStart + 1 + (wordEndMatch >= 0 ? wordEndMatch : afterMention.length);
    const before = content.slice(0, mentionStart);
    const after = content.slice(wordEnd);
    let handle = u.username;
    if (u.is_remote && u.remote_url) {
      try {
        const h = new URL(u.remote_url).hostname;
        if (h) handle = `${u.username}@${h}`;
      } catch {}
    }
    const inserted = `${before}@${handle} ${after}`;
    setContent(inserted);
    setMentionStart(-1);
    setMentionQuery("");
    setMentionUsers([]);
    requestAnimationFrame(() => {
      const ta = taRef.current;
      if (ta) {
        const pos = before.length + handle.length + 2;
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
    if (showSeriesSearch) {
      if (e.key === "Enter") {
        e.preventDefault();
        if (seriesResults.length > 0 && seriesResults[seriesIdx]) insertSeries(seriesResults[seriesIdx]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        const cur = content;
        const slashIdx = cur.lastIndexOf("/");
        if (slashIdx >= 0 && (cur.slice(slashIdx + 1).toLowerCase().startsWith("series") || cur.slice(slashIdx + 1).toLowerCase().startsWith("시리즈"))) {
          const after = cur.slice(slashIdx);
          const wordEndMatch = after.search(/[\s]|$/);
          const wordEnd = slashIdx + (wordEndMatch >= 0 ? wordEndMatch : after.length);
          setContent((cur.slice(0, slashIdx - 1) + cur.slice(wordEnd)).replace(/^\s+/, ""));
        }
        setShowSeriesSearch(false); setSeriesResults([]);
        return;
      }
    }
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

  const _isAllowedFile = (f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase() || "";
    const allowedExts = ["jpg", "jpeg", "png", "gif", "webp", "ico", "mp4", "webm"];
    return allowedExts.includes(ext) && (f.type.startsWith("image/") || f.type === "video/mp4" || f.type === "video/webm");
  };

  const handleMediaFiles = useCallback((files: File[]) => {
    setMediaWarning("");
    for (const f of files) {
      if (!_isAllowedFile(f)) continue;
      const isVideo = f.type === "video/mp4" || f.type === "video/webm";
      if (f.size > 26214400 && isVideo) { setMediaWarning("비디오는 25MB를 초과할 수 없습니다."); continue; }
      if (isVideo && mediaItems.some(m => m.type === "video")) continue;
      if (mediaItems.length >= 4) break;
      const id = ++mediaIdRef.current; setMediaItems(prev => [...prev, { id, url: "", type: isVideo ? "video" : "image", file: f }]);
    }
  }, [mediaItems]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files).filter(f => f.type.startsWith("image/") || f.type === "video/mp4" || f.type === "video/webm");
    if (files.length > 0) { e.preventDefault(); handleMediaFiles(files); }
  }, [handleMediaFiles]);

  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith("image/") || f.type === "video/mp4" || f.type === "video/webm");
    if (files.length > 0) handleMediaFiles(files);
  }, [handleMediaFiles]);

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
      const uploaded = mediaItems.filter(m => !m.file).map(m => ({ url: m.url, type: m.type, alt: m.alt || "" }));
      for (const m of mediaItems.filter(m => m.file)) {
        const formData = new FormData();
        formData.append("file", m.file!);
        const res = await fetch("/api/media/upload", { method: "POST", credentials: "include", body: formData });
        if (res.ok) { const d = await res.json(); uploaded.push({ url: d.url, type: d.type, alt: m.alt || "" }); }
      }
      const opts = showPoll ? pollOptions.filter(o => o.trim()).map(o => o.trim()) : [];
      const result = await api.createPost({ content, summary, visibility, parent_id: parentId, share_url: shareUrl, media_attachments: JSON.stringify(uploaded), is_sensitive: postSensitive, poll_options: opts.length >= 2 ? JSON.stringify(opts) : "", poll_expires_in: pollExpiresIn });
      setContent(""); setSummary(""); setPostSensitive(false); setMediaItems([]); setShowPoll(false); setPollOptions(["", ""]); setPollExpiresIn(24);
      if (onDone) onDone(result);
      else router.refresh();
    } catch (err: unknown) { alert(err instanceof Error ? err.message : "오류가 발생했습니다"); }
    setSubmitting(false);
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={`relative ${overLimit ? "over-limit" : nearLimit ? "near-limit" : ""}`} onClick={(e) => e.stopPropagation()} onDragOver={handleDragOver} onDrop={handleDrop}>
      {mediaWarning && <div style={{ fontSize: "0.85em", color: "var(--danger)", marginBottom: 6, padding: "4px 8px", background: "var(--bg-tertiary)", borderRadius: 6 }}>{mediaWarning}</div>}
      {mediaItems.length > 0 && (
        <div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {mediaItems.map((m, i) => (
              <div key={m.id} draggable style={{ position: "relative", width: 80, height: 80 }}
                onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(i)); (e.currentTarget as HTMLElement).style.opacity = "0.4"; }}
                onDragEnd={(e) => { (e.currentTarget as HTMLElement).style.opacity = "1"; }}
                onDragOver={(e) => { e.preventDefault(); }}
                onDrop={(e) => { e.preventDefault(); const from = parseInt(e.dataTransfer.getData("text/plain")); const to = i; if (from !== to) { const c = [...mediaItems]; const [removed] = c.splice(from, 1); c.splice(to, 0, removed); setMediaItems(c); } }}
              >
                {m.type === "video" ? (
                  <video src={m.url || (m.file ? URL.createObjectURL(m.file) : "")} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6, pointerEvents: "none" }} />
                ) : (
                  <img src={m.url || (m.file ? URL.createObjectURL(m.file) : "")} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6, pointerEvents: "none" }} />
                )}
                <span onClick={(e) => { e.stopPropagation(); setAltModalIdx(i); }} style={{ position: "absolute", bottom: -4, right: -4, width: 18, height: 18, borderRadius: "50%", background: m.alt ? "var(--accent)" : "var(--bg-secondary)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontStyle: "italic", cursor: "pointer", color: m.alt ? "#fff" : "var(--text-muted)" }} title="미디어 설명">a</span>
                <span onClick={(e) => { e.stopPropagation(); setMediaItems(mediaItems.filter((_, j) => j !== i)); }} style={{ position: "absolute", top: -4, right: -4, width: 18, height: 18, borderRadius: "50%", background: "var(--danger)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, cursor: "pointer" }}>×</span>
              </div>
            ))}
          </div>
          {altModalIdx !== null && (
            <div className="reply-modal-backdrop active" onClick={() => setAltModalIdx(null)}>
              <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 400 }}>
                <button className="reply-modal-close" onClick={() => setAltModalIdx(null)}>×</button>
                <h3>미디어 설명</h3>
                <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>시각 장애인을 위한 미디어 설명을 입력해주세요. 화면 낭독기에 전달됩니다.</p>
                <textarea
                  value={mediaItems[altModalIdx]?.alt || ""}
                  onChange={(e) => setMediaItems(prev => prev.map((item, j) => j === altModalIdx ? { ...item, alt: e.target.value } : item))}
                  placeholder="예: 푸른 하늘 아래 펼쳐진 녹색 언덕 위에 서있는 사람"
                  style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button onClick={() => setAltModalIdx(null)} className="btn btn-primary">확인</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
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
          onPaste={handlePaste}
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
        onChange={(e) => { setSummary(e.target.value); if (e.target.value && !postSensitive) setPostSensitive(true); }}
        placeholder="CW (선택사항)"
        className="cw-input"
        onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); } }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 13 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: !!summary ? "not-allowed" : "pointer", color: "var(--text-secondary)", opacity: !!summary ? 0.6 : 1 }}>
          <input type="checkbox" checked={postSensitive || !!summary} disabled={!!summary} onChange={(e) => setPostSensitive(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
          민감함
        </label>
        {(postSensitive || !!summary) && <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>{summary ? "CW 설정 시 자동 민감 처리됩니다" : "이 포스트의 모든 미디어가 블러 처리됩니다"}</span>}
      </div>
      {showPoll && (
        <div style={{ marginBottom: 8, padding: 10, borderRadius: 8, background: "var(--bg-tertiary)" }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--text-secondary)" }}>투표</div>
          {pollOptions.map((opt, i) => (
            <div key={i} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
              <input
                ref={i === pollOptions.length - 1 ? pollLastRef : undefined}
                type="text" placeholder={`선택지 ${i + 1}`}
                value={opt} maxLength={50}
                onChange={(e) => {
                  const next = [...pollOptions];
                  next[i] = e.target.value;
                  setPollOptions(next);
                  if (i === pollOptions.length - 1 && e.target.value.trim() && pollOptions.length < 10) {
                    setTimeout(() => {
                      setPollOptions((prev) => prev.length < 10 && prev[prev.length - 1] !== "" ? [...prev, ""] : prev);
                      setTimeout(() => pollLastRef.current?.focus(), 0);
                    }, 0);
                  }
                }}
                style={{ flex: 1, padding: "4px 8px", fontSize: 14, borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}
              />
              {pollOptions.length > 2 && (
                <button type="button" onClick={() => setPollOptions(pollOptions.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "var(--danger)", cursor: "pointer", fontSize: 16 }}>×</button>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
            {pollOptions.length < 10 && (
              <button type="button" className="action-btn" onClick={() => { setPollOptions([...pollOptions, ""]); setTimeout(() => pollLastRef.current?.focus(), 0); }} style={{ fontSize: 12 }}>+ 선택지 추가</button>
            )}
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>|</span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>마감</span>
            <select value={pollExpiresIn} onChange={(e) => setPollExpiresIn(Number(e.target.value))} style={{ fontSize: 12, padding: "2px 4px", borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
              <option value={5}>5분</option>
              <option value={30}>30분</option>
              <option value={60}>1시간</option>
              <option value={360}>6시간</option>
              <option value={720}>12시간</option>
              <option value={1440}>24시간</option>
              <option value={4320}>3일</option>
              <option value={10080}>7일</option>
            </select>
          </div>
        </div>
      )}
      <div className="reply-form-footer">
        <div className="vis-btn-wrap" style={{ position: "relative" }}>
          <button type="button" className="action-btn" onClick={() => setShowVisPicker(!showVisPicker)} title="공개 설정">
            <Icon name={visOpts.find(v => v.value === visibility)?.icon || "globe"} />
          </button>
          {showVisPicker && (
            <div className="vis-dropdown" style={{ position: "absolute", bottom: "100%", left: 0, background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, padding: 4, zIndex: 100, display: "flex", flexDirection: "column", gap: 2 }}>
              {visOpts.map(v => (
                <button key={v.value} type="button" className={`btn btn-small ${visibility === v.value ? "btn-primary" : "btn-outline"}`} onClick={() => { setVisibilityOverride(v.value); setShowVisPicker(false); }} style={{ textAlign: "left", justifyContent: "flex-start", gap: 6, whiteSpace: "nowrap" }}>
                  <Icon name={v.icon} size={14} /> {v.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="form-footer-right" style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
          <button type="button" className="action-btn" onClick={(e) => { e.stopPropagation(); mediaInputRef.current?.click(); }} title="미디어 첨부" disabled={mediaUploading || mediaItems.length >= 4}>
            <Icon name="image" />
          </button>
          <input ref={mediaInputRef} type="file" accept="image/*,video/mp4,video/webm" multiple hidden onChange={async (e) => {
            e.stopPropagation();
            const files = Array.from(e.target.files || []);
            handleMediaFiles(files);
            e.target.value = "";
          }} />
          <button type="button" className={`action-btn${showPoll ? " active" : ""}`} onClick={() => setShowPoll(!showPoll)} title="투표 추가" style={showPoll ? { color: "var(--accent)" } : undefined}>
            <Icon name="chart" />
          </button>
          <EmojiPicker alignRight onEmoji={(e) => setContent(content + e)} />
          <span className="char-count char-count-inline">{totalLen}/{MAX_LENGTH}</span>
          <button type="submit" disabled={submitting || !content.trim() || showSeriesSearch} className="btn btn-primary">
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
