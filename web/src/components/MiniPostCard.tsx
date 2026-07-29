"use client";
import { useState, useEffect, useMemo } from "react";
import { PostData } from "@/lib/api";
import Link from "next/link";
import Icon from "./Icon";
import { getCustomEmojis, renderCustomEmojis, CustomEmoji } from "@/lib/emojis";
import { sanitizePost, sanitizeName } from "@/lib/sanitize";
import { rewriteLinks } from "./PostCard";

const LIGHT_BG: Record<string, string> = {
  boost: "rgba(104, 159, 56, 0.1)",
  like: "rgba(241, 196, 15, 0.12)",
  poll_ended: "rgba(124, 77, 255, 0.1)",
};
const DARK_BG: Record<string, string> = {
  boost: "rgba(104, 159, 56, 0.15)",
  like: "rgba(241, 196, 15, 0.15)",
  poll_ended: "rgba(124, 77, 255, 0.15)",
};
const TYPE_ICONS: Record<string, string> = {
  follow: "user_solid", like: "star_filled", boost: "refresh",
  reply: "mention", mention: "mention", poll_ended: "chart",
};
const TYPE_COLORS: Record<string, string> = {
  boost: "var(--accent)",
  like: "#f1c40f",
  follow: "var(--text-muted)",
  reply: "var(--text-dim)",
  mention: "var(--text-dim)",
  poll_ended: "#7c4dff",
};

export default function MiniPostCard({ post, notifType, notifLabel }: { post: PostData; notifType?: string; notifLabel?: React.ReactNode }) {
  const [isDark, setIsDark] = useState(false);
  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);

  useEffect(() => { setIsDark(document.body.classList.contains("dark-theme")); }, []);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);
  const validMentions = useMemo(() => new Set(post.mentioned_handles || []), [post.mentioned_handles]);
  const bg = notifType
    ? (isDark ? DARK_BG[notifType] : LIGHT_BG[notifType]) || "var(--bg-tertiary)"
    : "var(--bg-tertiary)";
  const iconColor = notifType ? TYPE_COLORS[notifType] || "var(--text-muted)" : "var(--text-muted)";
  const contentHtml = (() => {
    let html = post.content || "";
    if (/<\/?[a-zA-Z]+[\s\/>]/.test(html) || /&[a-z]+;/.test(html)) {
      html = html.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
    } else {
      html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    html = renderCustomEmojis(html, emojiMap);
    return sanitizePost(rewriteLinks(html, validMentions));
  })();
  const makeUrl = ((post: any): string => {
    if (post.type === 'series' && post.author?.username && post.novel?.number) {
      return `/series/@${post.author.username}/${post.novel.number}`;
    }
    if (post.type === 'episode' && post.novel?.id && post.episode?.id) {
      return `/series/${post.novel.id}/episodes/${post.episode.id}`;
    }
    if (post.number && post.author?.username) {
      return `/@${post.author.username}/${post.number}`;
    }
    if (post.id) {
      return `/post/${post.id}`;
    }
    return '#'; // 모든 조건에 해당 안 될 때의 기본 안전 경로
  });

  if (!post || !post.author) return null;
  return (
    <>
    <Link
      href={makeUrl(post)}
      className="mini-post-link"
      style={{ background: bg }}
    >
      {!notifType && (
        <div className="mini-post-avatar-box">
          {post.author.avatar ? (
            <img src={post.author.avatar} alt="" className="mini-post-avatar-img" style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover" }} />
          ) : (
            <div className="mini-post-avatar-box-initials" style={{ background: `hsl(${post.author.username?.length * 37 % 360}, 35%, 40%)`, width: 28, height: 28, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>
              {(post.author.display_name || post.author.username)[0]}
            </div>
          )}
        </div>
      )}
      <div className="mini-post-content">
        {notifLabel && <div style={{ fontSize: "0.82em", color: "var(--text-muted)", marginBottom: 6, lineHeight: 1.4 }}>{notifLabel}</div>}
        {!notifType && (
          <div className="mini-post-author">
            <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.author.display_name || post.author.username, emojiMap, 14)) }} />
            <span className="mini-post-handle">
              @{post.author.display_handle || post.author.username}
            </span>
          </div>
        )}
        {post.summary && (
          <div className="mini-post-cw">
            CW: {post.summary}
          </div>
        )}
        {!post.summary && <div className="mini-post-body" dangerouslySetInnerHTML={{ __html: contentHtml }} />}
      </div>
    </Link>
    {(post as any).media_attachments?.length > 0 && (
      <div onClick={(e) => e.stopPropagation()} style={{ display: "grid", gridTemplateColumns: (post as any).media_attachments.length <= 2 ? "1fr" : "1fr 1fr", gridAutoRows: "120px", gap: 2, marginTop: 6, borderRadius: 6, overflow: "hidden" }}>
        {(post as any).media_attachments.slice(0, 4).map((m: any, i: number) => (
          m.type === "video" ? (
            <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", borderRadius: 4 }}>
              <video src={m.url} controls style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }} onClick={(e) => e.stopPropagation()} />
            </div>
          ) : (
            <img key={i} src={m.url} alt={m.alt || ""} style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000", borderRadius: 4, cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); window.open(m.url, '_blank'); }} />
          )
        ))}
      </div>
    )}
  </>
  );
}
