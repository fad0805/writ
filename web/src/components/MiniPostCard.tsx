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
  return text.replace(/(^|>|\s)@(\w+(?:@[\w.-]+)?)/g, (_m, before, handle) => {
    return `${before}<a href="/@${handle}" class="mention-link">@${handle}</a>`;
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
      style={{
        display: "flex",
        gap: 8,
        marginTop: 6,
        padding: "8px 10px",
        background: bg,
        border: "1px solid var(--border)",
        borderRadius: 8,
        color: "var(--text-primary)",
        fontSize: "0.85em",
        lineHeight: 1.5,
        textDecoration: "none",
      }}
    >
      {notifType ? (
        <div style={{ width: 28, height: 28, minWidth: 28, borderRadius: 6, background: "var(--bg-secondary)", display: "flex", alignItems: "center", justifyContent: "center", color: iconColor, marginTop: 1 }}>
          <Icon name={TYPE_ICONS[notifType] || "bell"} size={14} />
        </div>
      ) : (
        <div style={{ width: 28, height: 28, minWidth: 28, borderRadius: 6, background: `hsl(${post.author.username?.length * 37 % 360}, 35%, 40%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", fontSize: "0.85em", marginTop: 1 }}>
          {(post.author.display_name || post.author.username)[0]}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, color: "var(--accent)", marginBottom: 2 }}>
          {post.author.display_name}
          <span style={{ fontWeight: 400, color: "var(--text-dim)", marginLeft: 4 }}>
            @{post.author.username}
          </span>
        </div>
        {post.summary && (
          <div style={{ color: "var(--text-muted)", marginBottom: 4, fontSize: "0.85em" }}>
            CW: {post.summary}
          </div>
        )}
        <div style={{ wordBreak: "break-word" }} dangerouslySetInnerHTML={{ __html: contentHtml }} />
      </div>
    </Link>
  );
}
