"use client";
import { PostData, NovelData, User, api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import EditModal from "./EditModal";
import ReplyModal from "./ReplyModal";
import Icon from "./Icon";
import Avatar from "./Avatar";
import MiniPostCard from "./MiniPostCard";
import { useAuth } from "@/lib/auth";
import ShareButton from "@/components/ShareButton";
import { hashColor } from "@/lib/avatar";
import { getCustomEmojis, renderCustomEmojis, injectEmojis, CustomEmoji } from "@/lib/emojis";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

function rewriteLinks(text: string): string {
  // Replace external ActivityPub links with local handles
  text = text.replace(
    /<a\s+href="https?:\/\/([^"/]+)\/@(\w+)"[^>]*>@?\w*<\/a>/gi,
    (_m: string, domain: string, user: string) =>
      `<a href="/@${user}@${domain}" class="mention-link">@${user}@${domain}</a>`
  );
  // Convert plain @mentions outside of existing <a> tags
  return text.replace(/(^|>|\s)@(\w+(?:@[\w.-]+)?)/g, (_m, before, handle) => {
    return `${before}<a href="/@${handle}" class="mention-link">@${handle}</a>`;
  });
}

export default function PostCard({ post, onUpdate, onDelete, current, hideContext, selected, readonly }: { post: PostData; onUpdate?: () => void; onDelete?: () => void; current?: boolean; hideContext?: boolean; selected?: boolean; readonly?: boolean }) {
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const [showReply, setShowReply] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [liked, setLiked] = useState(post.liked);
  const [boosted, setBoosted] = useState(post.boosted);
  const [bookmarked, setBookmarked] = useState(post.bookmarked);
  const [likesCount, setLikesCount] = useState(post.likes_count);
  const [boostsCount, setBoostsCount] = useState(post.boosts_count);

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
    try { await api.deletePost(post.id); if (onDelete) onDelete(); else if (onUpdate) onUpdate(); } catch {}
  };

  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);

  const timeStr = post.created_at ? new Date(post.created_at).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).replace(/\. /g, "-").replace(/\.$/, "") : "";

  const [quoteUrl, setQuoteUrl] = useState("");
  const contentHtml = (() => {
    let html = post.content;
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    html = renderCustomEmojis(html, emojiMap);
    html = rewriteLinks(html);
    if (quoteUrl) {
      const escUrl = quoteUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      html = html.replace(new RegExp(`<a[^>]*>${escUrl}</a>`, 'gi'), '');
      html = html.replace(new RegExp(`series:\\s*${escUrl}`, 'gi'), '');
      html = html.replace(new RegExp(escUrl, 'gi'), '');
      html = html.replace(/<span class="quote-inline">\s*RE:\s*<\/span>/gi, '');
    }
    return html;
  })();

  // Extract quoted post URL from content
  type QuotedSeries = { type: "series"; novel: NovelData; author: User };
  const [quotedPost, setQuotedPost] = useState<PostData | null>(null);
  const [quotedSeries, setQuotedSeries] = useState<QuotedSeries | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  useEffect(() => {
    const newFormat = post.content.match(/https?:\/\/([^/]+)\/@(\w+(?:@[\w.-]+)?)\/([a-f0-9]+)/);
    const oldFormat = post.content.match(/https?:\/\/[^/]+\/post\/(\d+)/);
    const seriesFormat = post.content.match(/https?:\/\/[^/]+\/series\/(\d+)/);
    const seriesByNumber = post.content.match(/https?:\/\/[^/]+\/series\/by-number\/(\w+)\/([a-f0-9]+)/);
    const anyUrl = post.content.match(/https?:\/\/[^\s<>"']+/);
    const url = seriesFormat?.[0] || seriesByNumber?.[0] || newFormat?.[0] || oldFormat?.[0] || anyUrl?.[0];
    if (!url) return;
    setQuoteUrl(url);
    setLoadingQuote(true);
    const isLocal = (url.match(/https?:\/\/([^/]+)/)?.[1]) === window.location.host;
    if (isLocal && (seriesFormat || seriesByNumber)) {
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
          <Link href={`/@${post.author.username}`} className="post-author" onClick={(e) => e.stopPropagation()}>
            {post.author.display_name} {(post.author.role === "admin" || post.author.role === "moderator") && (post.author as any).show_badge && <Icon name="shield_filled" style={{ color: post.author.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 2 }} title={post.author.role === "admin" ? "관리자" : "조율자"} />}
          </Link>
          <Link href={`/@${post.author.username}`} className="post-username" onClick={(e) => e.stopPropagation()}>
            @{post.author.username}
          </Link>
          {post.author.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.65em", verticalAlign: "middle", color: "var(--text-muted)", marginLeft: 2 }} />}
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
              let html = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
              html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
              html = html.replace(/\n/g, '<br>');
              html = renderCustomEmojis(html, emojiMap);
              html = rewriteLinks(html);
              if ((post.reply_context.content || "").length > 90) html += "...";
              return html;
            })() }} />
          </Link>
        )}
        {post.summary ? (
          <details className="cw-box" onClick={(e) => e.stopPropagation()}>
            <summary onClick={(e) => e.stopPropagation()}>⚠️ {post.summary}</summary>
            <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
          </details>
        ) : (
          <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
        )}
        {loadingQuote && <div className="empty-small" style={{ padding: "8px 0" }}>인용 불러오는 중...</div>}
        {quotedPost && <div className="my-8"><MiniPostCard post={quotedPost} /></div>}
        {quotedSeries && (
          <div className="quoted-series" onClick={(e) => { e.stopPropagation(); router.push(`/series/${quotedSeries.novel.id}`); }}>
              <div className="cover-wrap-64 bg-tertiary">
              {quotedSeries.novel.cover_image ? (
                <img src={quotedSeries.novel.cover_image} alt="" className="cover-img" />
              ) : (
                <div className="cover-fallback" style={{ backgroundColor: hashColor(quotedSeries.novel.title), fontSize: "1em" }}>
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
        {!readonly && <div className="post-actions" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setShowReply(!showReply); }} className="action-btn">
            <Icon name="reply" /> {post.replies_count}
          </button>
          <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
            <button type="button" onClick={toggleLike} className={`action-btn ${liked ? "liked" : ""}`}>
              <Icon name={liked ? "star_filled" : "star"} /> {likesCount}
            </button>
          </form>
          <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
            <button type="button" onClick={toggleBoost} className={`action-btn ${boosted ? "boosted" : ""}`}>
              <Icon name="refresh" /> {boostsCount}
            </button>
          </form>
            <button onClick={(e) => { e.stopPropagation(); toggleBookmark(); }} className={`action-btn${bookmarked ? " bookmarked" : ""}`} style={{ color: bookmarked ? "#5b7db5" : undefined }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill={bookmarked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
          </button>
          <ShareButton url={post.ap_id?.startsWith("http") ? post.ap_id : (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`)} />
          <div className="spacer" />
          {(post.is_mine || currentUser?.is_admin) && (
            <>
              <button onClick={() => setShowEdit(true)} className="action-btn">
                <Icon name="edit" />
              </button>
              <button onClick={handleDelete} className="action-btn action-btn-danger">
                <Icon name="trash" />
              </button>
            </>
          )}
        </div>}
      </div>
      {!readonly && showReply && <ReplyModal post={post} onClose={() => setShowReply(false)} onDone={() => { setShowReply(false); if (onUpdate) onUpdate(); }} />}
      {!readonly && showEdit && <EditModal post={post} onClose={() => setShowEdit(false)} onDone={() => { setShowEdit(false); if (onUpdate) onUpdate(); }} />}
    </>
  );
}
