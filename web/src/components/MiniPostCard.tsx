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
    let html = post.content;
    if (/<\/?[a-zA-Z]+[\s>]/.test(html) || /&[a-z]+;/.test(html)) {
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
  return (
    <Link
      href={post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`}
      className="mini-post-link"
      style={{ background: bg }}
    >
      {notifType ? (
        <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: iconColor }}>
          <Icon name={TYPE_ICONS[notifType] || "bell"} size={14} />
        </div>
      ) : (
        <div className="mini-post-avatar-box">
          {post.author.avatar ? (
            <img src={post.author.avatar} alt="" className="mini-post-avatar-img" style={{ width: 36, height: 36, borderRadius: "50%", objectFit: "cover" }} />
          ) : (
            <div className="mini-post-avatar-box-initials" style={{ background: `hsl(${post.author.username?.length * 37 % 360}, 35%, 40%)`, width: 36, height: 36, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>
              {(post.author.display_name || post.author.username)[0]}
            </div>
          )}
        </div>
      )}
      <div className="mini-post-content">
        {notifLabel && <div style={{ fontSize: "0.82em", color: "var(--text-muted)", marginBottom: 3, lineHeight: 1.4 }}>{notifLabel}</div>}
        <div className="mini-post-author">
          <span dangerouslySetInnerHTML={{ __html: renderCustomEmojis(post.author.display_name || post.author.username, emojiMap) }} />
          <span className="mini-post-handle">
            @{post.author.display_handle || post.author.username}
          </span>
        </div>
        {post.summary && (
          <div className="mini-post-cw">
            CW: {post.summary}
          </div>
        )}
        <div className="mini-post-body" dangerouslySetInnerHTML={{ __html: contentHtml }} />
      </div>
    </Link>
  );
}
