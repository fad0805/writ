"use client";
import { useState, useEffect } from "react";
import { PostData } from "@/lib/api";
import Link from "next/link";
import Icon from "./Icon";
import { getCustomEmojis, renderCustomEmojis, CustomEmoji } from "@/lib/emojis";

function rewriteLinks(text: string): string {
  text = text.replace(
    /<a\s+href="https?:\/\/([^"/]+)\/@(\w+)"[^>]*>@?\w*<\/a>/gi,
    (_m: string, domain: string, user: string) =>
      `<a href="/@${user}@${domain}" class="mention-link">@${user}@${domain}</a>`
  );
  text = text.replace(/(^|>|\s)@(\w+(?:@[\w.-]+)?)/g, (_m, before, handle) => {
    return `${before}<a href="/@${handle}" class="mention-link">@${handle}</a>`;
  });
  return text.replace(/(^|>|\s)#([\w_가-힣]+)/g, (_m, before, tag) => {
    return `${before}<a href="/explore?q=%23${encodeURIComponent(tag)}" class="hashtag-link">#${tag}</a>`;
  });
}

const LIGHT_BG: Record<string, string> = {
  boost: "rgba(104, 159, 56, 0.1)",
  like: "rgba(241, 196, 15, 0.12)",
};
const DARK_BG: Record<string, string> = {
  boost: "rgba(104, 159, 56, 0.15)",
  like: "rgba(241, 196, 15, 0.15)",
};
const TYPE_ICONS: Record<string, string> = {
  follow: "user_solid", like: "star_filled", boost: "refresh",
  reply: "mention", mention: "mention",
};
const TYPE_COLORS: Record<string, string> = {
  boost: "var(--accent)",
  like: "#f1c40f",
  follow: "var(--text-muted)",
  reply: "var(--text-dim)",
  mention: "var(--text-dim)",
};

export default function MiniPostCard({ post, notifType }: { post: PostData; notifType?: string }) {
  const [isDark, setIsDark] = useState(false);
  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  useEffect(() => { setIsDark(document.body.classList.contains("dark-theme")); }, []);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);
  const bg = notifType
    ? (isDark ? DARK_BG[notifType] : LIGHT_BG[notifType]) || "var(--bg-tertiary)"
    : "var(--bg-tertiary)";
  const iconColor = notifType ? TYPE_COLORS[notifType] || "var(--text-muted)" : "var(--text-muted)";
  const contentHtml = (() => {
    let html = post.content;
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    html = renderCustomEmojis(html, emojiMap);
    return rewriteLinks(html);
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
        <div className="mini-post-avatar-box mini-post-avatar-box-initials" style={{ background: `hsl(${post.author.username?.length * 37 % 360}, 35%, 40%)` }}>
          {(post.author.display_name || post.author.username)[0]}
        </div>
      )}
      <div className="mini-post-content">
        <div className="mini-post-author">
          {post.author.display_name}
          <span className="mini-post-handle">
            @{post.author.username}
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
