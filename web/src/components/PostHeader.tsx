"use client";
import React, { useEffect, useState } from "react";
import { PostData, PostEditVersion, api } from "@/lib/api";
import { CustomEmoji, renderCustomEmojis } from "@/lib/emojis";
import { sanitizeName, sanitizePost, sanitizeSummary } from "@/lib/sanitize";
import Link from "next/link";
import Avatar from "./Avatar";
import Icon from "./Icon";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

function formatEditTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).replace(/\. /g, "-").replace(/\.$/, "");
}

export function PostEditHistoryModal({ postId, onClose }: { postId: number; onClose: () => void }) {
  const [versions, setVersions] = useState<PostEditVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.getPostEdits(postId)
      .then((data) => { if (!cancelled) setVersions(data.versions || []); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [postId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="reply-modal-backdrop active" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="reply-modal edit-history-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>수정 내역</h3>
        {loading && <p className="empty-small">불러오는 중...</p>}
        {error && <p className="empty-small">수정 내역을 불러오지 못했습니다: {error}</p>}
        {!loading && !error && versions.length === 0 && (
          <p className="empty-small">이전 버전 기록이 없습니다.</p>
        )}
        {!loading && !error && versions.map((v) => (
          <section key={`${v.version}-${v.is_current ? "current" : "old"}`} className={`edit-history-version${v.is_current ? " current" : ""}`}>
            <header className="edit-history-version-head">
              <strong>{v.is_current ? "현재" : v.version === 0 ? "원본" : `수정 ${v.version}`}</strong>
              {v.created_at && <span>{formatEditTime(v.created_at)}</span>}
            </header>
            {v.summary && (
              <div className="edit-history-summary" dangerouslySetInnerHTML={{ __html: sanitizeSummary(v.summary) }} />
            )}
            <div className="edit-history-content" dangerouslySetInnerHTML={{ __html: sanitizePost(v.content) }} />
          </section>
        ))}
      </div>
    </div>
  );
}

export default React.memo(function PostHeader({ post, mergedEmojiList, timeStr, postHref, timeHref, onShowEdits }: {
  post: PostData;
  mergedEmojiList: CustomEmoji[];
  timeStr: string;
  postHref: string;
  timeHref?: string;
  onShowEdits?: () => void;
}) {
  const finalTimeHref = timeHref || postHref;
  const editedLabel = formatEditTime(post.edited_at);
  return (
    <div className="post-header">
      <Link href={`/@${post.author.username}`} className="post-author-avatar-link no-underline" onClick={(e) => e.stopPropagation()}>
        <Avatar user={post.author} className="post-author-avatar flex items-center justify-center text-white font-bold text-sm" />
      </Link>
      <div className="post-name-wrap">
        <Link href={`/@${post.author.username}`} className="post-author" onClick={(e) => e.stopPropagation()}>
          <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.author.display_name, mergedEmojiList, 14)) }} /> {(post.author.role === "admin" || post.author.role === "moderator" || post.author.role === "owner") && post.author.show_badge && <Icon name={post.author.role === "owner" ? "books_solid" : "shield_filled"} style={{ color: post.author.role === "owner" ? "var(--accent)" : post.author.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 2 }} title={post.author.role === "owner" ? "오너" : post.author.role === "admin" ? "관리자" : "조율자"} />}
        </Link>
        <Link href={`/@${post.author.username}`} className="post-username" onClick={(e) => e.stopPropagation()}>
          @{post.author.display_handle || post.author.username}
        </Link>
      </div>
      <span className="post-time">
        <span className={`vis-badge vis-${post.visibility}`}>
          <Icon name={VIS_ICONS[post.visibility] || "globe"} />
        </span>
        {timeStr ? <Link href={finalTimeHref} className="no-underline" style={{ color: "inherit" }}>{timeStr}</Link> : null}
        {post.edited_at && (
          onShowEdits ? (
            <button
              type="button"
              className="post-edited-badge"
              title={editedLabel ? `마지막 수정: ${editedLabel}` : "수정된 게시글"}
              onClick={(e) => { e.stopPropagation(); onShowEdits(); }}
            >
              수정됨
            </button>
          ) : (
            <Link
              href={postHref}
              className="post-edited-badge no-underline"
              title={editedLabel ? `마지막 수정: ${editedLabel}` : "수정된 게시글"}
              onClick={(e) => e.stopPropagation()}
            >
              수정됨
            </Link>
          )
        )}
      </span>
    </div>
  );
});
