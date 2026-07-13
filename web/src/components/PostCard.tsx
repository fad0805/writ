"use client";
import { PostData, NovelData, User, EpisodeData, api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useMemo } from "react";
import EditModal from "./EditModal";
import ReplyModal from "./ReplyModal";
import ClickableCover from "./ClickableCover";
import Icon from "./Icon";
import Avatar from "./Avatar";
import MiniPostCard from "./MiniPostCard";
import EmojiPicker from "./EmojiPicker";
import { useAuth } from "@/lib/auth";
import ShareButton from "@/components/ShareButton";
import { hashColor } from "@/lib/avatar";
import { getCustomEmojis, renderCustomEmojis, injectEmojis, CustomEmoji } from "@/lib/emojis";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  if (abs < 60000) return `${Math.floor(abs / 1000)}초`;
  if (abs < 3600000) return `${Math.floor(abs / 60000)}분 ${Math.floor((abs % 60000) / 1000)}초`;
  if (abs < 86400000) return `${Math.floor(abs / 3600000)}시간`;
  return `${Math.floor(abs / 86400000)}일`;
}

function rewriteLinks(text: string, validMentions?: Set<string>): string {
  text = text.replace(
    /<a\s+href="https?:\/\/([^"/]+)\/@([a-zA-Z_][a-zA-Z0-9_]*)"[^>]*>@?\w*<\/a>/gi,
    (_m: string, domain: string, user: string) =>
      `<a href="/@${user}@${domain}" class="mention-link">@${user}@${domain}</a>`
  );

  text = text.replace(/(^|>|\s)@([a-zA-Z_][a-zA-Z0-9_]*(?:@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})?)/g, (_m, before, handle) => {
    return `${before}<a href="/@${handle}" class="mention-link">@${handle}</a>`;
  });

  text = text.replace(/(^|>|\s)#([\w_가-힣]+)/g, (_m, before, tag) => {
    return `${before}<a href="/explore?q=%23${encodeURIComponent(tag)}" class="hashtag-link">#${tag}</a>`;
  });

  text = text.replace(/(^|>|　|\s)(https?:\/\/[^\s<>"')\]]+)(?![\s\S]*?<\/a>)/g, (_m: string, before: string, url: string) => {
    return `${before}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
  });

  return text;
}

export default function PostCard({ post, onUpdate, onDelete, onReply, current, hideContext, selected, readonly }: { post: PostData; onUpdate?: () => void; onDelete?: () => void; onReply?: (newPost?: PostData) => void; current?: boolean; hideContext?: boolean; selected?: boolean; readonly?: boolean }) {
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const [showReply, setShowReply] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [showPollResults, setShowPollResults] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [reportReason, setReportReason] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(false);
  const [reportForward, setReportForward] = useState(false);
  const [reportRules, setReportRules] = useState<{ id: number; title: string; description: string }[]>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<number[]>([]);
  const [liked, setLiked] = useState(post.liked);
  const [boosted, setBoosted] = useState(post.boosted);
  const [bookmarked, setBookmarked] = useState(post.bookmarked);
  const [pinned, setPinned] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [likesCount, setLikesCount] = useState(post.likes_count);
  const [boostsCount, setBoostsCount] = useState(post.boosts_count);
  const [serverLogo, setServerLogo] = useState("");
  useEffect(() => {
    fetch("/api/server-info").then(r=>r.json()).then(d=>setServerLogo(d.logo||"")).catch(()=>{});
  }, []);
  const [reactions, setReactions] = useState(post.reactions || {});
  const [myReaction, setMyReaction] = useState(post.my_reaction || null);
  const [reactionEmojiMap, setReactionEmojiMap] = useState<Record<string, string>>(() => {
    if ((window as any).__emojiMap) return (window as any).__emojiMap;
    fetch("/api/emojis").then(r=>r.json()).then((list: any[]) => {
      const m: Record<string, string> = {};
      for (const e of list) if (e.keyword && e.url) m[e.keyword] = e.url;
      (window as any).__emojiMap = m;
      setReactionEmojiMap(m);
    }).catch(() => {});
    return {};
  });

  useEffect(() => {
    if (currentUser?.pinned_posts) setPinned(currentUser.pinned_posts.includes(post.id));
  }, [currentUser, post.id]);

  useEffect(() => {
    if (!post.poll_data) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [post.poll_data]);

  const toggleLike = async () => {
    try {
      if (liked) { await api.unlike(post.id); setLiked(false); setLikesCount(Math.max(0, likesCount - 1)); }
      else { await api.like(post.id); setLiked(true); setLikesCount(likesCount + 1); }
    } catch {}
  };

  const toggleBookmark = async () => {
    try {
      if (bookmarked) { await api.unbookmark(post.id); setBookmarked(false); }
      else { await api.bookmark(post.id); setBookmarked(true); }
    } catch {}
  };

  const toggleBoost = async () => {
    try {
      if (boosted) { await api.unboost(post.id); setBoosted(false); setBoostsCount(Math.max(0, boostsCount - 1)); }
      else { await api.boost(post.id); setBoosted(true); setBoostsCount(boostsCount + 1); }
    } catch {}
  };

  const handleDelete = async () => {
    const isAdminDeletingOther = currentUser?.is_admin && !post.is_mine;
    if (!confirm(isAdminDeletingOther ? "관리자 권한으로 이 게시글을 삭제하시겠습니까?" : "삭제하시겠습니까?")) return;
    if (onDelete) onDelete();
    else if (onUpdate) onUpdate();
    else if (current) router.back();
    try { await api.deletePost(post.id); } catch {}
  };

  const handleReport = async () => {
    if (selectedRuleIds.length === 0 && reportReason.trim().length < 10) { setReportError("규칙을 선택하거나 사유를 10자 이상 입력해주세요."); return; }
    setReportError("");
    try {
      const form = new FormData();
      form.append("target_type", "post");
      form.append("target_id", String(post.id));
      form.append("reason", reportReason.trim());
      form.append("forward_to_remote", reportForward ? "true" : "");
      form.append("rule_ids", JSON.stringify(selectedRuleIds));
      const res = await fetch("/api/reports", { method: "POST", credentials: "include", body: form });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "신고 실패"); }
      setReportDone(true);
      setShowReport(false);
    } catch (e: any) {
      setReportError(e.message || "신고 처리 중 오류가 발생했습니다.");
    }
  };

  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);

  const [nowTime, setNowTime] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNowTime(Date.now()), 10000); return () => clearInterval(id); }, []);
  const timeStr = post.created_at ? (() => {
    const t = new Date(post.created_at).getTime();
    const diff = nowTime - t;
    if (diff < 86400000) {
      if (diff < 60000) return `${Math.floor(diff / 1000)}초 전`;
      if (diff < 3600000) return `${Math.floor(diff / 60000)}분 전`;
      return `${Math.floor(diff / 3600000)}시간 전`;
    }
    return new Date(post.created_at).toLocaleString("ko-KR", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).replace(/\. /g, "-").replace(/\.$/, "");
  })() : "";

  const [quoteUrl, setQuoteUrl] = useState("");
  const validMentions = useMemo(() => new Set(post.mentioned_handles || []), [post.mentioned_handles]);
  const [resolvedMentions, setResolvedMentions] = useState<Map<string, string>>(new Map());
  const buildContentHtml = (qUrl?: string, resolved?: Map<string, string>) => {
    let html = post.content;
    html = html.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    html = renderCustomEmojis(html, emojiMap);
    html = rewriteLinks(html, validMentions);
    if (resolved && resolved.size) {
      resolved.forEach((localUser, handle) => {
        const escaped = handle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        html = html.replace(
          new RegExp(`<a\\s+href="/@${escaped}"[^>]*>[^<]*<\\/a>`, "g"),
          `<a href="/@${localUser}" class="mention-link">@${localUser}</a>`
        );
      });
    }
    if (qUrl) {
      const escUrl = qUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const hasPrefix = new RegExp(`(series:|episode:)\\s*${escUrl}`, 'i').test(html);
      if (hasPrefix) {
        html = html.replace(new RegExp(`<a[^>]*>${escUrl}<\\/a>`, 'gi'), '');
        html = html.replace(new RegExp(`(series:|episode:)\\s*${escUrl}`, 'gi'), '');
        html = html.replace(new RegExp(escUrl, 'gi'), '');
      } else {
        const host = typeof window !== 'undefined' ? window.location.host : '';
        const isLocal = host === (qUrl.match(/https?:\/\/([^/]+)/)?.[1]);
        const linkHref = isLocal ? qUrl.replace(/https?:\/\/[^/]+/, '') : qUrl;
        const linkTarget = isLocal ? '' : ' target="_blank" rel="noopener noreferrer"';
        const inAnchorRe = new RegExp(`<a\\s+href="[^"]*${escUrl}[^"]*"[^>]*>[\\s\\S]*?<\\/a>`, 'gi');
        if (inAnchorRe.test(html)) {
          html = html.replace(new RegExp(`<a(\\s+)href="[^"]*${escUrl}[^"]*"`), `<a$1href="${linkHref}"${linkTarget}`);
        } else {
          html = html.replace(new RegExp(`(^|>|　|\\s)${escUrl}`, 'gi'), `$1<a href="${linkHref}"${linkTarget}>${qUrl}</a>`);
        }
      }
      html = html.replace(/<span class="quote-inline">\s*RE:\s*<\/span>/gi, '');
    }
    return html;
  };
  const [contentHtml, setContentHtml] = useState(() => buildContentHtml());

  useEffect(() => {
    const mentionRe = /<a\s+href="\/@([a-zA-Z_][a-zA-Z0-9_]*(?:@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}))"[^>]*>[^<]*<\/a>/g;
    const remoteMentions: string[] = [];
    let m: RegExpExecArray | null;
    while ((m = mentionRe.exec(contentHtml)) !== null) {
      const handle = m[1];
      if (handle.includes("@") && !validMentions.has(handle) && !resolvedMentions.has(handle)) {
        remoteMentions.push(handle);
      }
    }
    if (!remoteMentions.length) return;
    const seen = new Set<string>();
    remoteMentions.forEach((handle) => {
      if (seen.has(handle)) return;
      seen.add(handle);
      const [username, domain] = handle.split("@");
      const profileUrl = `https://${domain}/@${username}`;
      const form = new FormData();
      form.append("url", profileUrl);
      fetch("/api/fetch-actor", { method: "POST", credentials: "include", body: form })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data?.username) {
            setResolvedMentions((prev) => {
              const next = new Map(prev);
              next.set(handle, data.username);
              return next;
            });
          }
        })
        .catch(() => {});
    });
  }, []);
  useEffect(() => {
    setContentHtml(buildContentHtml(quoteUrl || undefined, resolvedMentions));
  }, [quoteUrl, resolvedMentions, emojiMap]);

  // Extract quoted post URL from content
  type QuotedSeries = { type: "series"; novel: NovelData; author: User };
  type QuotedEpisode = { type: "episode"; episode: EpisodeData; novel: NovelData; author: User };
  const [quotedPost, setQuotedPost] = useState<PostData | null>(null);
  const [quotedSeries, setQuotedSeries] = useState<QuotedSeries | null>(null);
  const [quotedEpisode, setQuotedEpisode] = useState<QuotedEpisode | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [viewerIndex, setViewerIndex] = useState(-1);
  const [revealedSensitive, setRevealedSensitive] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (viewerIndex < 0) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewerIndex(-1);
      else if (e.key === "ArrowLeft" && viewerIndex > 0) setViewerIndex(viewerIndex - 1);
      else if (e.key === "ArrowRight" && viewerIndex < (post as any).media_attachments.length - 1) setViewerIndex(viewerIndex + 1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [viewerIndex]);
  useEffect(() => {
    if (!showMoreActions) return;
    const handler = () => setShowMoreActions(false);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [showMoreActions]);
  useEffect(() => {
    const newFormat = post.content.match(/https?:\/\/([^/]+)\/@(\w+(?:@[\w.-]+)?)\/([a-f0-9]+)/);
    const oldFormat = post.content.match(/https?:\/\/[^/]+\/post\/(\d+)/);
    const seriesFormat = post.content.match(/https?:\/\/[^/]+\/series\/(\d+)/);
    const seriesByNumber = post.content.match(/https?:\/\/[^/]+\/series\/by-number\/(\w+)\/([a-f0-9]+)/);
    const episodeFormat = post.content.match(/https?:\/\/[^/]+\/series\/(\d+)\/episodes\/(\d+)/);
    const anyUrl = post.content.match(/https?:\/\/[^\s<>"']+/);
    const url = episodeFormat?.[0] || seriesFormat?.[0] || seriesByNumber?.[0] || newFormat?.[0] || oldFormat?.[0] || anyUrl?.[0];
    if (!url) return;
    setQuoteUrl(url);
    setLoadingQuote(true);
    const isLocal = (url.match(/https?:\/\/([^/]+)/)?.[1]) === window.location.host;
    if (isLocal && episodeFormat) {
      fetch("/api/fetch-episode", { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ url }) })
        .then(r => { if (r.ok) return r.json(); throw new Error(); })
        .then(d => { setQuotedEpisode(d); setLoadingQuote(false); })
        .catch(() => setLoadingQuote(false));
    } else if (isLocal && (seriesFormat || seriesByNumber)) {
      fetch("/api/fetch-series", { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ url }) })
        .then(r => { if (r.ok) return r.json(); throw new Error(); })
        .then(d => { setQuotedSeries(d); setLoadingQuote(false); })
        .catch(() => setLoadingQuote(false));
    } else if (newFormat) {
      const domain = newFormat[1];
      const username = newFormat[2];
      const number = newFormat[3];
      if (isLocal) {
        fetch(`/api/by-number/${username}/${number}`, { credentials: "include" })
          .then(r => r.json()).then(d => { setQuotedPost(d); setLoadingQuote(false); })
          .catch(() => setLoadingQuote(false));
      } else {
        const fullUrl = `https://${domain}/@${username}/${number}`;
        const form = new FormData(); form.append("url", fullUrl);
        fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form })
          .then(r => r.json()).then(d => { if (d._emojis) { injectEmojis(d._emojis); getCustomEmojis().then(setEmojiMap); } setQuotedPost(d); setLoadingQuote(false); })
          .catch(() => setLoadingQuote(false));
      }
    } else if (oldFormat) {
      const postId = oldFormat[1];
      fetch(`/api/posts/${postId}?reply_limit=0&reply_offset=0`, { credentials: "include" })
        .then(r => r.json()).then(d => { setQuotedPost(d); setLoadingQuote(false); })
        .catch(() => setLoadingQuote(false));
    } else {
      const form = new FormData(); form.append("url", anyUrl![0]);
      fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form })
        .then(r => { if (r.ok) return r.json(); throw new Error(); })
        .then(d => {
          if (d._emojis) {
            injectEmojis(d._emojis);
            // Immediately update emoji map so render picks it up
            getCustomEmojis().then(setEmojiMap);
          }
          setQuotedPost(d);
          setLoadingQuote(false);
        })
        .catch(() => setLoadingQuote(false));
    }
  }, [post.content]);

  const handleContentClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href');
    if (href && href.startsWith('/')) {
      e.preventDefault();
      e.stopPropagation();
      router.push(href);
    }
  };

  const _renderMedia = () => (
    <div className="post-media-grid" style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(((post as any).media_attachments || []).length, 2)}, 1fr)`, gap: 4, marginTop: 8 }}>
      {(post as any).media_attachments.slice(0, 16).map((m: any, i: number) => {
        const postSensitive = (post as any).is_sensitive || (post.author as any)?.is_sensitive || !!(post as any).summary;
        const isSensitive = postSensitive && !revealedSensitive.has(i);
        const revealed = postSensitive && revealedSensitive.has(i);
        return m.type === "video" ? (
          <div key={i} style={{ position: "relative", lineHeight: 0 }}>
            {isSensitive && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 1, cursor: "pointer", color: "#fff", fontSize: 13, fontWeight: 600 }} onClick={(e) => { e.stopPropagation(); e.preventDefault(); setRevealedSensitive((prev) => new Set(prev).add(i)); }}><span style={{ fontSize: 12, fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>클릭하여 표시</span></div>}
            {revealed && <button onClick={(e) => { e.stopPropagation(); setRevealedSensitive((prev) => { const n = new Set(prev); n.delete(i); return n; }); }} style={{ position: "absolute", top: 4, right: 4, zIndex: 2, background: "rgba(0,0,0,0.6)", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, padding: "3px 10px", cursor: "pointer" }}>가리기</button>}
            <video src={m.url} controls style={{ width: "100%", maxHeight: 300, borderRadius: 8, objectFit: "contain", background: "#000", filter: isSensitive ? "blur(20px)" : "none" }} />
          </div>
        ) : (
          <div key={i} style={{ position: "relative", lineHeight: 0 }}>
            {isSensitive && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 8, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 1, cursor: "pointer", color: "#fff", fontSize: 13, fontWeight: 600 }} onClick={(e) => { e.stopPropagation(); e.preventDefault(); setRevealedSensitive((prev) => new Set(prev).add(i)); }}><span style={{ fontSize: 12, fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>클릭하여 표시</span></div>}
            {revealed && <button onClick={(e) => { e.stopPropagation(); setRevealedSensitive((prev) => { const n = new Set(prev); n.delete(i); return n; }); }} style={{ position: "absolute", top: 4, right: 4, zIndex: 2, background: "rgba(0,0,0,0.6)", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, padding: "3px 10px", cursor: "pointer" }}>가리기</button>}
            <img key={i} src={m.url} alt={m.alt || ""} style={{ width: "100%", maxHeight: 300, borderRadius: 8, objectFit: "contain", background: "#000", cursor: "pointer", filter: isSensitive ? "blur(20px)" : "none" }} onClick={(e) => { if (!isSensitive) { e.stopPropagation(); setViewerIndex(i); } }} />
          </div>
        );
      })}
    </div>
  );

  return (
    <>
      <div className={`post-card${current ? " current" : ""}${selected ? " selected" : ""}${post.visibility === "mention" ? " mention-card" : ""}`} onClick={(e) => { if (current || (e.target as HTMLElement).closest('a')) return; router.push(post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`); }}>
        {post.boosted_by && (
          <div className="boost-badge">
            <Icon name="refresh" size={12} /> {post.boosted_by.display_name || post.boosted_by.username}님이 부스트
          </div>
        )}
        <div className="post-header">
          <Link href={`/@${post.author.username}`} className="post-author-avatar-link no-underline" onClick={(e) => e.stopPropagation()}>
            <Avatar user={post.author} className="post-author-avatar flex items-center justify-center text-white font-bold text-sm" />
          </Link>
          <div className="post-name-wrap">
            <Link href={`/@${post.author.username}`} className="post-author" onClick={(e) => e.stopPropagation()}>
              {post.author.display_name} {(post.author.role === "admin" || post.author.role === "moderator" || post.author.role === "owner") && (post.author as any).show_badge && <Icon name={post.author.role === "owner" ? "books_solid" : "shield_filled"} style={{ color: post.author.role === "owner" ? "var(--accent)" : post.author.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 2 }} title={post.author.role === "owner" ? "오너" : post.author.role === "admin" ? "관리자" : "조율자"} />}
            </Link>
            <Link href={`/@${post.author.username}`} className="post-username" onClick={(e) => e.stopPropagation()}>
              @{post.author.display_handle || post.author.username}
            </Link>
            {post.author.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.65em", verticalAlign: "middle", color: "var(--text-muted)", marginLeft: 2 }} />}
          </div>
          <span className="post-time">
            <span className={`vis-badge vis-${post.visibility}`}>
              <Icon name={VIS_ICONS[post.visibility] || "globe"} />
            </span>
            {post.ap_id && post.ap_id.startsWith("http") && post.author?.username?.includes("@") ? (
              <a href={post.ap_id} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="no-underline" style={{ color: "inherit" }}>{timeStr}</a>
            ) : (
              timeStr
            )}
          </span>
        </div>
        {!hideContext && post.reply_context && (
          <Link href={post.reply_context.number ? `/@${post.reply_context.author.username}/${post.reply_context.number}` : `/post/${post.reply_context.id}`} className={`reply-context${post.reply_context.visibility === "mention" ? " mention-context" : ""}`} onClick={(e) => e.stopPropagation()}>
            <span className="reply-context-label">답글 대상</span>
            <strong>{post.reply_context.author.display_name || post.reply_context.author.username}</strong>
            <span>@{post.reply_context.author.username}</span>
            <p dangerouslySetInnerHTML={{ __html: (() => {
              const text = (post.reply_context.content || "").slice(0, 90);
              let html = text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
              html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
              html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
              html = html.replace(/\n/g, '<br>');
              html = renderCustomEmojis(html, emojiMap);
              html = rewriteLinks(html, validMentions);
              if ((post.reply_context.content || "").length > 90) html += "...";
              return html;
            })() }} />
          </Link>
        )}
        {post.summary ? (
          <details className="cw-box" onClick={(e) => e.stopPropagation()}>
            <summary onClick={(e) => e.stopPropagation()}>⚠️ {post.summary}</summary>
            <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
            {(post as any).media_attachments?.length > 0 && _renderMedia()}
          </details>
        ) : (
          <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
        )}
        {!post.summary && (post as any).media_attachments?.length > 0 && _renderMedia()}
        {post.poll_data && (
          (() => {
            const total = post.poll_data!.options.reduce((s, o) => s + (o.votes_count || 0), 0);
            const isExpired = post.poll_data!.expires_at && new Date(post.poll_data!.expires_at).getTime() < now;
            const showResults = showPollResults || post.my_vote != null || isExpired || readonly || post.is_mine;
            return <div className="poll-box" style={{ marginTop: 8, padding: 10, borderRadius: 8, background: "var(--bg-tertiary)" }}>
              {post.poll_data!.options.map((opt, i) => {
                const pct = showResults && total > 0 ? Math.round(((opt.votes_count || 0) / total) * 100) : 0;
                const isSelected = post.my_vote === i;
                const canVote = !showResults && !isExpired && post.my_vote == null && !readonly && !post.is_mine;
                return (
                  <div
                    key={i}
                    className={`poll-option${isSelected ? " selected" : ""}${canVote ? " votable" : ""}`}
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!canVote) return;
                      try {
                        const result = await api.vote(post.id, i);
                        if (result.post) {
                          Object.assign(post, result.post);
                        }
                        if (onUpdate) onUpdate();
                        else window.dispatchEvent(new Event("postchange"));
                      } catch (err: any) { alert(err.message); }
                    }}
                    style={{
                      position: "relative", padding: "8px 10px", marginBottom: 4, borderRadius: 6,
                      border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                      background: isSelected ? "color-mix(in srgb, var(--accent) 15%, transparent)" : "var(--bg-secondary)",
                      cursor: canVote ? "pointer" : "default", overflow: "hidden",
                      transition: "all 0.15s",
                    }}
                  >
                    {showResults && <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${pct}%`, background: "color-mix(in srgb, var(--accent) 12%, transparent)", borderRadius: 6, transition: "width 0.3s" }} />}
                    <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontWeight: isSelected ? 600 : 400, fontSize: 14 }}>{opt.text}</span>
                      {showResults && <span style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 40, textAlign: "right" }}>{pct}%</span>}
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
                <span>총 {total}표</span>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {!showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(true); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>결과 보기</button>
                  )}
                  {showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(false); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>투표하기</button>
                  )}
                  {post.poll_data!.expires_at ? (
                    new Date(post.poll_data!.expires_at).getTime() < now ? <span>종료</span> : <span>{formatRelative(post.poll_data!.expires_at, now)}</span>
                  ) : null}
                </span>
              </div>
            </div>;
          })()
        )}
        {loadingQuote && <div className="empty-small loading-small">인용 불러오는 중...</div>}
        {quotedPost && <div className="my-8"><MiniPostCard post={quotedPost} /></div>}
        {quotedSeries && (
          <div className="quoted-series" onClick={(e) => { e.stopPropagation(); router.push(`/series/${quotedSeries.novel.id}`); }}>
              <div className="cover-wrap-64 bg-tertiary">
              {quotedSeries.novel.cover_image ? (
                <ClickableCover src={quotedSeries.novel.cover_image} isSensitive={(quotedSeries.novel as any).is_sensitive} className="cover-img" />
              ) : (
                serverLogo ? <img src={serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
                : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedSeries.novel.title) }}>
                  {quotedSeries.novel.title[0]}
                </div>
              )}
            </div>
            <div className="mini-post-content">
              <div className="mini-post-cw"><Icon name="book" /> 시리즈</div>
              <div className="emoji-keyword">{quotedSeries.novel.title}</div>
              {quotedSeries.author && <div className="text-sm text-muted">by {quotedSeries.author.display_name || quotedSeries.author.username}</div>}
              {quotedSeries.novel.description && <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedSeries.novel.description.slice(0, 100)}</div>}
            </div>
          </div>
        )}
        {quotedEpisode && (
          <div className="quoted-series" onClick={(e) => { e.stopPropagation(); router.push(`/series/${quotedEpisode.novel.id}/episodes/${quotedEpisode.episode.id}`); }}>
            <div className="cover-wrap-64 bg-tertiary">
              {quotedEpisode.novel.cover_image ? (
                <ClickableCover src={quotedEpisode.novel.cover_image} isSensitive={(quotedEpisode.novel as any).is_sensitive} className="cover-img" />
              ) : (
                serverLogo ? <img src={serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
                : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedEpisode.novel.title) }}>
                  {quotedEpisode.novel.title[0]}
                </div>
              )}
            </div>
            <div className="mini-post-content">
              <div className="mini-post-cw"><Icon name="book" /> 에피소드</div>
              <div className="emoji-keyword">{quotedEpisode.novel.title} — {quotedEpisode.episode.title}</div>
              {quotedEpisode.author && <div className="text-sm text-muted">by {quotedEpisode.author.display_name || quotedEpisode.author.username}</div>}
              {quotedEpisode.episode.summary ? (
                <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.summary}</div>
              ) : (
                <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").slice(0, 50)}{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").length > 50 ? "..." : ""}</div>
              )}
            </div>
          </div>
        )}
        {post.link_preview && (
          <a href={post.link_preview.url} target="_blank" rel="noopener noreferrer" className="link-preview-card" onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 12, marginTop: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
            {post.link_preview.image && <img src={post.link_preview.image} alt="" style={{ width: 80, height: 80, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} onError={(e) => (e.target as HTMLElement).style.display = "none"} />}
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{post.link_preview.title}</div>
              {post.link_preview.description && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{post.link_preview.description}</div>}
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{(() => { try { return new URL(post.link_preview!.url).hostname; } catch { return ""; } })()}</div>
            </div>
          </a>
        )}
          {reactions && Object.keys(reactions).length > 0 && (
          <div className="reactions-row" style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8, marginBottom: 4, padding: "0 8px" }} onClick={(e) => e.stopPropagation()}>
            {currentUser?.enable_reactions !== false ? (
              Object.entries(reactions).sort(([a], [b]) => a === "★" ? -1 : b === "★" ? 1 : 0).map(([emoji, count]) => {
              const emojiKey = emoji.startsWith(":") && emoji.endsWith(":") ? emoji.slice(1, -1) : emoji;
              const isNotLocalCustom = emoji.startsWith(":") && emoji.endsWith(":") && !reactionEmojiMap[emojiKey];
              return (
              <span
                key={emoji}
                className={`reaction-badge${myReaction === emoji ? " active" : ""}${isNotLocalCustom ? " reaction-disabled" : ""}`}
                onClick={isNotLocalCustom ? undefined : async () => {
                  if (myReaction === emoji) {
                    await api.unreact(post.id);
                    const next = { ...reactions };
                    if (next[emoji] <= 1) delete next[emoji];
                    else next[emoji] -= 1;
                    setReactions(next);
                    setMyReaction(null);
                    setLiked(false);
                    setLikesCount(Math.max(0, likesCount - 1));
                  } else {
                    await api.react(post.id, emoji);
                    setReactions({ ...reactions, [emoji]: (reactions[emoji] || 0) + 1 });
                    setMyReaction(emoji);
                    setLiked(true);
                    setLikesCount(likesCount + 1);
                  }
                }}
                style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 13, cursor: isNotLocalCustom ? "default" : "pointer", border: "1px solid var(--border)", background: myReaction === emoji ? "color-mix(in srgb, var(--accent) 20%, transparent)" : "var(--bg-secondary)", opacity: isNotLocalCustom ? 0.5 : 1 }}
              >
{emoji === "★" ? (
                  <Icon name="star_filled" size={18} style={{ color: "#f1c40f" }} />
                ) : emoji.startsWith(":") && emoji.endsWith(":") ? (
                  reactionEmojiMap[emojiKey]
                    ? <img src={reactionEmojiMap[emojiKey]} alt={emoji} style={{ height: 22, verticalAlign: "middle" }} />
                    : <span>{emoji}</span>
                ) : (
                  <span>{emoji}</span>
                )}
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{count}</span>
              </span>
            );
            })
            ) : (
              <span className="reaction-badge" style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 8px", borderRadius: 12, fontSize: 13, border: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
                <Icon name="star_filled" size={18} style={{ color: "#f1c40f" }} />
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{Object.values(reactions).reduce((a: number, b: number) => a + b, 0)}</span>
              </span>
            )}
          </div>
        )}
        {!readonly && <div className="post-actions" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setShowReply(!showReply); }} className="action-btn">
            <Icon name="reply" /> {post.replies_count}
          </button>
          <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
            <button type="button" onClick={toggleBoost} className={`action-btn ${boosted ? "boosted" : ""}`}>
              <Icon name="refresh" /> {boostsCount}
            </button>
          </form>
          {currentUser?.enable_reactions !== false ? (
            <span onClick={(e) => e.stopPropagation()} className="relative-wrap" style={{ marginBottom: -2 }}>
              <EmojiPicker onEmoji={async (emoji) => {
                try {
                  await api.react(post.id, emoji);
                  setReactions({ ...reactions, [emoji]: (reactions[emoji] || 0) + 1 });
                  setMyReaction(emoji);
                  setLiked(true);
                  setLikesCount(likesCount + 1);
                } catch {}
              }} />
            </span>
          ) : (
            <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
              <button type="button" onClick={toggleLike} className={`action-btn ${liked ? "liked" : ""}`}>
                <Icon name={myReaction && liked ? "star_filled" : liked ? "star_filled" : "star"} /> {likesCount}
              </button>
            </form>
          )}
          <button onClick={(e) => { e.stopPropagation(); toggleBookmark(); }} className={`action-btn${bookmarked ? " bookmarked" : ""}`} style={{ color: bookmarked ? "#5b7db5" : undefined }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill={bookmarked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
          </button>
          {(post.is_mine || currentUser?.is_admin || currentUser && !post.is_mine) && (
            <div className="post-actions-more" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => setShowMoreActions(!showMoreActions)} className="action-btn post-actions-more-btn">
                <Icon name="more_horizontal" />
              </button>
              {showMoreActions && (
                <div className="post-actions-dropdown">
                  <ShareButton url={post.ap_id?.startsWith("http") ? post.ap_id : (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`)} className="post-actions-dropdown-item" />
                  {post.is_mine && (
                    <button onClick={() => { setShowMoreActions(false); (async () => {
                      const newPinned = !pinned;
                      setPinned(newPinned);
                      const res = await fetch(`/api/${newPinned ? "pin" : "unpin"}/post/${post.id}`, { method: "POST", credentials: "include" });
                      if (!res.ok) { setPinned(!newPinned); const d = await res.json().catch(() => ({})); if (d.detail) alert(d.detail); }
                      else { window.dispatchEvent(new Event("pinchange")); window.dispatchEvent(new Event("profilechange")); }
                    })(); }} className="post-actions-dropdown-item">
                      <Icon name={pinned ? "pin_filled" : "pin"} /> {pinned ? "고정 해제" : "고정"}
                    </button>
                  )}
                  {(post.is_mine || currentUser?.is_admin) && (
                    <>
                      <button onClick={() => { setShowMoreActions(false); setShowEdit(true); }} className="post-actions-dropdown-item">
                        <Icon name="edit" /> 수정
                      </button>
                      <button onClick={() => { setShowMoreActions(false); handleDelete(); }} className="post-actions-dropdown-item post-actions-dropdown-danger">
                        <Icon name="trash" /> 삭제
                      </button>
                    </>
                  )}
                  {currentUser && !post.is_mine && (
                    <button onClick={() => { setShowMoreActions(false); setShowReport(true); setReportReason(""); setReportError(""); setReportDone(false); setSelectedRuleIds([]); fetch("/api/rules").then(r => r.json()).then(setReportRules).catch(() => {}); }} className="post-actions-dropdown-item">
                      <Icon name="flag" /> 신고
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>}
      </div>
      {!readonly && showReply && <ReplyModal post={post} onClose={() => setShowReply(false)} onDone={(newPost) => { setShowReply(false); if (onReply) onReply(newPost); else if (onUpdate) onUpdate(); }} />}
      {!readonly && showEdit && <EditModal post={post} onClose={() => setShowEdit(false)} onDone={() => { setShowEdit(false); if (onUpdate) onUpdate(); }} />}
      {!readonly && showReport && (
        <div className="reply-modal-backdrop active" onClick={() => setShowReport(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <button className="reply-modal-close" onClick={() => setShowReport(false)}>×</button>
            <h3>게시글 신고</h3>
            {reportDone ? (
              <p style={{ color: "var(--text-secondary)", margin: "16px 0" }}>신고가 접수되었습니다. 검토 후 조치하겠습니다.</p>
            ) : (
              <>
                {reportRules.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--text-secondary)" }}>위반 규칙</p>
                    {reportRules.map((rule) => (
                      <label key={rule.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 4, borderRadius: 6, border: selectedRuleIds.includes(rule.id) ? "1px solid var(--accent)" : "1px solid var(--border)", background: selectedRuleIds.includes(rule.id) ? "var(--bg-tertiary)" : "var(--bg-secondary)", cursor: "pointer", transition: "all 0.15s" }}>
                        <input type="checkbox" checked={selectedRuleIds.includes(rule.id)} onChange={(e) => setSelectedRuleIds((prev) => e.target.checked ? [...prev, rule.id] : prev.filter((id) => id !== rule.id))} style={{ marginTop: 2, accentColor: "var(--accent)" }} />
                        <span style={{ fontSize: 13, color: "var(--text)" }}><strong>{rule.title}</strong>{rule.description ? <span style={{ color: "var(--text-secondary)" }}>{` — ${rule.description}`}</span> : ""}</span>
                      </label>
                    ))}
                  </div>
                )}
                <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: "var(--text-secondary)" }}>기타 사유</p>
                <textarea
                  value={reportReason}
                  onChange={(e) => setReportReason(e.target.value)}
                  placeholder={selectedRuleIds.length > 0 ? "추가 사유 (선택)" : "신고 사유를 입력해주세요 (최소 10자)"}
                  style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
                />
                {reportError && <p style={{ color: "var(--error)", fontSize: 14, marginBottom: 8 }}>{reportError}</p>}
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 8, color: "var(--text-secondary)", cursor: "pointer" }}>
                  <input type="checkbox" checked={reportForward} onChange={(e) => setReportForward(e.target.checked)} />
                  원격 서버로 신고 전송
                </label>
                <button onClick={handleReport} className="btn" style={{ width: "100%" }}>신고 제출</button>
              </>
            )}
          </div>
        </div>
      )}
      {viewerIndex >= 0 && (post as any).media_attachments?.length > 0 && (
        <div className="reply-modal-backdrop active" onClick={() => setViewerIndex(-1)}>
          <div className="media-viewer" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "90vw", maxHeight: "90vh", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
            {(viewerIndex > 0) && (
              <button onClick={(e) => { e.stopPropagation(); setViewerIndex(viewerIndex - 1); }} style={{ position: "absolute", left: -50, top: "50%", transform: "translateY(-50%)", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20 }}>‹</button>
            )}
            {(viewerIndex < (post as any).media_attachments.length - 1) && (
              <button onClick={(e) => { e.stopPropagation(); setViewerIndex(viewerIndex + 1); }} style={{ position: "absolute", right: -50, top: "50%", transform: "translateY(-50%)", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20 }}>›</button>
            )}
            <button onClick={() => setViewerIndex(-1)} style={{ position: "absolute", top: -40, right: 0, background: "none", border: "none", color: "#fff", fontSize: 28, cursor: "pointer", zIndex: 10 }}>×</button>
            {(() => {
              const m = (post as any).media_attachments[viewerIndex];
              return m?.type === "video" ? (
                <video src={m.url} controls style={{ maxWidth: "100%", maxHeight: "85vh", borderRadius: 8 }} />
              ) : (
                <img src={m.url} alt={m.alt || ""} style={{ maxWidth: "100%", maxHeight: "85vh", borderRadius: 8, objectFit: "contain" }} />
              );
            })()}
          </div>
        </div>
      )}
    </>
  );
}


