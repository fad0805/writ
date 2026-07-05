"use client";
import { PostData, api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import EditModal from "./EditModal";
import ReplyModal from "./ReplyModal";
import Icon from "./Icon";
import Avatar from "./Avatar";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

function linkifyMentions(text: string): string {
  return text.replace(/@(\w+)/g, '<a href="/profile/$1" class="mention-link">@$1</a>');
}

export default function PostCard({ post, onUpdate, current, hideContext }: { post: PostData; onUpdate?: () => void; current?: boolean; hideContext?: boolean }) {
  const router = useRouter();
  const [showReply, setShowReply] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [liked, setLiked] = useState(post.liked);
  const [boosted, setBoosted] = useState(post.boosted);
  const [likesCount, setLikesCount] = useState(post.likes_count);
  const [boostsCount, setBoostsCount] = useState(post.boosts_count);

  const toggleLike = async () => {
    try {
      if (liked) { await api.unlike(post.id); setLiked(false); setLikesCount(Math.max(0, likesCount - 1)); }
      else { await api.like(post.id); setLiked(true); setLikesCount(likesCount + 1); }
    } catch {}
  };

  const toggleBoost = async () => {
    try {
      if (boosted) { await api.unboost(post.id); setBoosted(false); setBoostsCount(Math.max(0, boostsCount - 1)); }
      else { await api.boost(post.id); setBoosted(true); setBoostsCount(boostsCount + 1); }
    } catch {}
  };

  const handleDelete = async () => {
    if (!confirm("삭제하시겠습니까?")) return;
    try { await api.deletePost(post.id); if (onUpdate) onUpdate(); } catch {}
  };

  const timeStr = post.created_at ? new Date(post.created_at).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).replace(/\. /g, "-").replace(/\.$/, "") : "";

  const contentHtml = linkifyMentions(post.content);

  return (
    <>
      <div className={`post-card${current ? " current" : ""}`} onClick={(e) => { if ((e.target as HTMLElement).closest('a')) return; router.push(`/post/${post.id}`); }}>
        {post.boosted_by && (
          <div className="boost-badge">
            <Icon name="refresh" size={12} /> {post.boosted_by.display_name || post.boosted_by.username}님이 부스트
          </div>
        )}
        <div className="post-header">
          <Link href={`/profile/${post.author.username}`} className="post-author-avatar-link" onClick={(e) => e.stopPropagation()} style={{ textDecoration: "none" }}>
            <Avatar user={post.author} className="post-author-avatar flex items-center justify-center text-white font-bold text-sm" />
          </Link>
          <Link href={`/profile/${post.author.username}`} className="post-author" onClick={(e) => e.stopPropagation()}>
            {post.author.display_name}
          </Link>
          <Link href={`/profile/${post.author.username}`} className="post-username" onClick={(e) => e.stopPropagation()}>
            @{post.author.username}
          </Link>
          <span className="post-time">
            <span className={`vis-badge vis-${post.visibility}`}>
              <Icon name={VIS_ICONS[post.visibility] || "globe"} />
            </span>
            {timeStr}
          </span>
        </div>
        {!hideContext && post.reply_context && (
          <Link href={`/post/${post.reply_context.id}`} className="reply-context" onClick={(e) => e.stopPropagation()}>
            <span className="reply-context-label">답글 대상</span>
            <strong>{post.reply_context.author.display_name || post.reply_context.author.username}</strong>
            <span>@{post.reply_context.author.username}</span>
            <p>{(post.reply_context.content || "").replace(/\n/g, " ").slice(0, 90)}{(post.reply_context.content || "").length > 90 ? "..." : ""}</p>
          </Link>
        )}
        {post.summary ? (
          <details className="cw-box" onClick={(e) => e.stopPropagation()}>
            <summary onClick={(e) => e.stopPropagation()}>⚠️ {post.summary}</summary>
            <div className="post-content" dangerouslySetInnerHTML={{ __html: contentHtml }} />
          </details>
        ) : (
          <div className="post-content" dangerouslySetInnerHTML={{ __html: contentHtml }} />
        )}
        <div className="post-actions" onClick={(e) => e.stopPropagation()}>
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
          <div className="spacer" />
          {post.is_mine && (
            <>
              <button onClick={() => setShowEdit(true)} className="action-btn">
                <Icon name="edit" />
              </button>
              <button onClick={handleDelete} className="action-btn action-btn-danger">
                <Icon name="trash" />
              </button>
            </>
          )}
        </div>
      </div>
      {showReply && <ReplyModal post={post} onClose={() => setShowReply(false)} onDone={() => { setShowReply(false); if (onUpdate) onUpdate(); }} />}
      {showEdit && <EditModal post={post} onClose={() => setShowEdit(false)} onDone={() => { setShowEdit(false); if (onUpdate) onUpdate(); }} />}
    </>
  );
}
