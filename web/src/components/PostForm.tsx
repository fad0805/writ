"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { api, PostData } from "@/lib/api";
import Icon from "@/components/Icon";
import { useRouter } from "next/navigation";
import TextareaHighlight from "./TextareaHighlight";
import EmojiPicker from "./EmojiPicker";
import { useAuth } from "@/lib/auth";
import { useComposerAutocomplete } from "@/hooks/useComposerAutocomplete";
import ComposerMedia from "./ComposerMedia";
import ComposerLinkPreview from "./ComposerLinkPreview";
import ComposerPoll from "./ComposerPoll";

const MAX_LENGTH = 500;

export default function PostForm({ parentId, onDone, placeholder, initialContent, initialVisibility, shareUrl, parentSummary, initialSummary, initialMedia }: { parentId?: number; onDone?: (post?: PostData) => void; placeholder?: string; initialContent?: string; initialVisibility?: string; shareUrl?: string; parentSummary?: string | null; initialSummary?: string | null; initialMedia?: { url: string; type: string; alt?: string }[] }) {
  const draftKey = `draft_${parentId || "new"}`;
  const savedDraft = typeof localStorage !== "undefined" ? (() => { try { return JSON.parse(localStorage.getItem(draftKey) || "null"); } catch { return null; } })() : null;
  const [content, setContent] = useState((shareUrl ? initialContent : (savedDraft?.content ?? initialContent)) || "");
  const [summary, setSummary] = useState((shareUrl ? undefined : savedDraft?.summary) ?? (initialSummary !== undefined ? initialSummary : (parentId && parentSummary ? parentSummary : "")));
  const [postSensitive, setPostSensitive] = useState(shareUrl ? false : (savedDraft?.sensitive ?? false));
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

  const autocomplete = useComposerAutocomplete({ content, setContent, taRef, shareUrl });
  const {
    emoji: { results: emojiResults, idx: emojiIdx, pos: emojiPos, setIdx: setEmojiIdx, onKeyDown: emojiOnKeyDown, detect: detectEmoji },
    mention: { results: mentionUsers, idx: mentionIdx, pos: mentionPos, setIdx: setMentionIdx, onKeyDown: mentionOnKeyDown, detect: detectMention },
    hashtag: { results: hashtagResults, idx: hashtagIdx, pos: hashtagPos, setIdx: setHashtagIdx, onKeyDown: hashtagOnKeyDown, detect: detectHashtag },
    series: { show: showSeriesSearch, query: seriesSearchQ, results: seriesResults, idx: seriesIdx, pos: seriesPos, setQuery: setSeriesSearchQ, setIdx: setSeriesIdx, inputRef: seriesSearchRef, detect: detectSeries, insert: insertSeries, onKeyDown: seriesOnKeyDown },
    linkPreview,
    setLinkPreview,
    linkPreviewLoading,
    quoteUrl,
    setQuoteUrl,
    quotePost,
    setQuotePost,
    insertEmoji,
    insertMention,
    insertHashtag,
  } = autocomplete;
  const mediaIdRef = useRef(0);
  const [mediaItems, setMediaItems] = useState<{ id: number; url: string; type: string; file?: File; alt?: string; preview?: string }[]>(() =>
    (initialMedia || []).map((m, i) => ({ id: -(i + 1), url: m.url, type: m.type || "image", alt: m.alt || "" }))
  );
  const revokeMediaPreviews = useCallback((items: { preview?: string }[]) => {
    for (const m of items) if (m.preview) URL.revokeObjectURL(m.preview);
  }, []);
  const [mediaUploading, setMediaUploading] = useState(false);
  const [mediaWarning, setMediaWarning] = useState("");
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const [showVisPicker, setShowVisPicker] = useState(false);
  const [showPoll, setShowPoll] = useState(false);
  const [pollOptions, setPollOptions] = useState<string[]>(["", ""]);
  const [pollExpiresIn, setPollExpiresIn] = useState(1440);
  const pollLastRef = useRef<HTMLInputElement>(null);
  const [altModalIdx, setAltModalIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!showVisPicker) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as Element)?.closest?.(".vis-btn-wrap")) setShowVisPicker(false);
    };
    setTimeout(() => document.addEventListener("click", close), 0);
    return () => document.removeEventListener("click", close);
  }, [showVisPicker]);

  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    const t = setTimeout(() => {
      if (content || summary || postSensitive) {
        localStorage.setItem(draftKey, JSON.stringify({ content, summary, sensitive: postSensitive }));
      } else {
        localStorage.removeItem(draftKey);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [content, summary, postSensitive, draftKey]);

  const totalLen = content.length + summary.length;
  const nearLimit = totalLen > MAX_LENGTH - 50 && totalLen <= MAX_LENGTH;
  const overLimit = totalLen > MAX_LENGTH;

  const handleTaEvent = useCallback((e: React.KeyboardEvent | React.MouseEvent) => {
    const el = e.target as HTMLTextAreaElement;
    detectMention(el.value, el.selectionStart);
    detectEmoji(el.value, el.selectionStart);
    detectHashtag(el.value, el.selectionStart);
    detectSeries(el.value, el.selectionStart);
  }, [detectMention, detectEmoji, detectHashtag, detectSeries]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (seriesOnKeyDown(e)) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      formRef.current?.requestSubmit();
      return;
    }
    if (emojiOnKeyDown(e, insertEmoji)) return;
    if (mentionOnKeyDown(e, insertMention)) return;
    if (hashtagOnKeyDown(e, insertHashtag)) return;
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
    const allowedExts = ["jpg", "jpeg", "png", "gif", "webp", "ico", "mp4", "webm", "mp3", "m4a", "aac", "wav", "flac", "ogg"];
    return allowedExts.includes(ext) && (f.type.startsWith("image/") || f.type.startsWith("audio/") || f.type === "video/mp4" || f.type === "video/webm");
  };

  const handleMediaFiles = useCallback((files: File[]) => {
    setMediaWarning("");
    for (const f of files) {
      if (!_isAllowedFile(f)) continue;
      const isVideo = f.type === "video/mp4" || f.type === "video/webm";
      const isAudio = f.type.startsWith("audio/");
      if (f.size > 26214400 && isVideo) { setMediaWarning("비디오는 25MB를 초과할 수 없습니다."); continue; }
      if (f.size > 20 * 1024 * 1024 && isAudio) { setMediaWarning("오디오는 20MB를 초과할 수 없습니다."); continue; }
      if (isVideo && mediaItems.some(m => m.type === "video")) continue;
      if (isAudio && mediaItems.some(m => m.type === "audio")) continue;
      if (mediaItems.length >= 4) break;
      const id = ++mediaIdRef.current; setMediaItems(prev => [...prev, { id, url: "", type: isVideo ? "video" : isAudio ? "audio" : "image", file: f, preview: URL.createObjectURL(f) }]);
    }
  }, [mediaItems]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files).filter(f => f.type.startsWith("image/") || f.type.startsWith("audio/") || f.type === "video/mp4" || f.type === "video/webm");
    if (files.length > 0) { e.preventDefault(); handleMediaFiles(files); }
  }, [handleMediaFiles]);

  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith("image/") || f.type.startsWith("audio/") || f.type === "video/mp4" || f.type === "video/webm");
    if (files.length > 0) handleMediaFiles(files);
  }, [handleMediaFiles]);

  const resetForm = useCallback(() => {
    setContent("");
    setSummary("");
    setPostSensitive(false);
    revokeMediaPreviews(mediaItems);
    setMediaItems([]);
    setShowPoll(false);
    setPollOptions(["", ""]);
    setPollExpiresIn(1440);
    setLinkPreview(null);
    setQuoteUrl("");
    setQuotePost(null);
  }, [mediaItems, revokeMediaPreviews]);

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
      const filesToUpload = mediaItems.filter(m => m.file);
      if (filesToUpload.length > 0) {
        setMediaUploading(true);
        const results = await Promise.all(filesToUpload.map(async (m) => {
          const formData = new FormData();
          formData.append("file", m.file!);
          const res = await fetch("/api/media/upload", { method: "POST", credentials: "include", body: formData });
          if (res.ok) { const d = await res.json(); return { url: d.url, type: d.type, alt: m.alt || "" }; }
          return null;
        }));
        const failedCount = results.filter(r => !r).length;
        if (failedCount > 0) {
          throw new Error(`${failedCount}개의 미디어 업로드에 실패했습니다.`);
        }
        results.forEach(r => { if (r) uploaded.push(r); });
      }
      const opts = showPoll ? pollOptions.filter(o => o.trim()).map(o => o.trim()) : [];
      let shareUrlFinal = quoteUrl || shareUrl;
      if (!shareUrlFinal) {
        const urlMatch = content.match(/https?:\/\/[^\s<>"')\]]+/i);
        if (urlMatch) shareUrlFinal = urlMatch[0].replace(/[.,;:!?)]+$/, "");
      }
      const result = await api.createPost({ content, summary, visibility, parent_id: parentId, share_url: shareUrlFinal, media_attachments: JSON.stringify(uploaded), is_sensitive: postSensitive, poll_options: opts.length >= 2 ? JSON.stringify(opts) : "", poll_expires_in: pollExpiresIn, link_preview: linkPreview ? JSON.stringify(linkPreview) : "" });
      resetForm();
      if (typeof localStorage !== "undefined") localStorage.removeItem(draftKey);
      window.dispatchEvent(new CustomEvent("writ:draft-cleared", { detail: { key: draftKey } }));
      if (onDone) onDone(result);
      else router.refresh();
    } catch (err: unknown) { alert(err instanceof Error ? err.message : "오류가 발생했습니다"); }
    setSubmitting(false);
    setMediaUploading(false);
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className={`relative ${overLimit ? "over-limit" : nearLimit ? "near-limit" : ""}`} onClick={(e) => e.stopPropagation()} onDragOver={handleDragOver} onDrop={handleDrop}>
      {mediaWarning && <div style={{ fontSize: "0.85em", color: "var(--danger)", marginBottom: 6, padding: "4px 8px", background: "var(--bg-tertiary)", borderRadius: 6 }}>{mediaWarning}</div>}
      {mediaItems.length > 0 && (
        <ComposerMedia items={mediaItems} setItems={setMediaItems} altIdx={altModalIdx} setAltIdx={setAltModalIdx} revokePreviews={revokeMediaPreviews} />
      )}
      {(quotePost || quoteUrl) && <ComposerLinkPreview quotePost={quotePost} quoteUrl={quoteUrl} linkPreview={linkPreview} linkPreviewLoading={linkPreviewLoading} onClearQuote={() => { setQuoteUrl(""); setQuotePost(null); }} onClearPreview={() => setLinkPreview(null)} />}
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
      <div style={{ position: "relative", marginBottom: 10 }}>
        <input
          type="text"
          value={summary}
          onChange={(e) => { setSummary(e.target.value); if (e.target.value && !postSensitive) setPostSensitive(true); }}
          placeholder="CW (선택사항)"
          className="cw-input"
          style={{ marginBottom: 0, ...(summary ? { paddingRight: 28 } : {}) }}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); } }}
        />
        {summary && (
          <button
            type="button"
            aria-label="CW 초기화"
            onClick={() => { setSummary(""); setPostSensitive(false); formRef.current?.querySelector<HTMLInputElement>(".cw-input")?.focus(); }}
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", display: "flex", padding: 2, lineHeight: 1 }}
          >
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 13 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: !!summary ? "not-allowed" : "pointer", color: "var(--text-secondary)", opacity: !!summary ? 0.6 : 1 }}>
          <input type="checkbox" checked={postSensitive || !!summary} disabled={!!summary} onChange={(e) => setPostSensitive(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
          민감함
        </label>
        {(postSensitive || !!summary) && <span style={{ color: "var(--text-secondary)", fontSize: 12 }}>{summary ? "CW 설정 시 자동 민감 처리됩니다" : "이 포스트의 모든 미디어가 블러 처리됩니다"}</span>}
      </div>
      {showPoll && (
        <ComposerPoll options={pollOptions} setOptions={setPollOptions} expiresIn={pollExpiresIn} setExpiresIn={setPollExpiresIn} lastRef={pollLastRef} />
      )}
      <div className="reply-form-footer">
        <div className="vis-btn-wrap" style={{ position: "relative" }}>
          <button type="button" className="action-btn" data-vis={visibility} onClick={() => setShowVisPicker(!showVisPicker)} title="공개 설정">
            <Icon name={visOpts.find(v => v.value === visibility)?.icon || "globe"} />
          </button>
          {showVisPicker && (
            <div className="vis-dropdown" style={{ position: "absolute", bottom: "100%", left: 0, background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, padding: 4, zIndex: 100, display: "flex", flexDirection: "column", gap: 2 }}>
              {visOpts.map(v => (
                <button key={v.value} type="button" className={`btn btn-small ${visibility === v.value ? "btn-primary" : "btn-outline"}`} data-vis={v.value} onClick={() => { setVisibilityOverride(v.value); setShowVisPicker(false); }} style={{ textAlign: "left", justifyContent: "flex-start", gap: 6, whiteSpace: "nowrap" }}>
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
          <input ref={mediaInputRef} type="file" accept="image/*,video/mp4,video/webm,audio/*" multiple hidden onChange={async (e) => {
            e.stopPropagation();
            const files = Array.from(e.target.files || []);
            handleMediaFiles(files);
            e.target.value = "";
          }} />
          <button type="button" className={`action-btn${showPoll ? " active" : ""}`} onClick={() => setShowPoll(!showPoll)} title="투표 추가" style={showPoll ? { color: "var(--accent)" } : undefined}>
            <Icon name="chart" />
          </button>
          <EmojiPicker onEmoji={(e) => {
            const ta = taRef.current;
            const pos = ta && ta.selectionStart != null ? ta.selectionStart : content.length;
            const end = ta && ta.selectionEnd != null ? ta.selectionEnd : content.length;
            const inserted = e + " ";
            setContent((prev: string) => prev.slice(0, pos) + inserted + prev.slice(end));
            requestAnimationFrame(() => {
              if (ta) {
                const p = pos + inserted.length;
                ta.setSelectionRange(p, p);
                ta.focus();
              }
            });
          }} />
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
