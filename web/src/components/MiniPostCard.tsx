"use client";
import { useState, useEffect, useMemo } from "react";
import { PostData } from "@/lib/api";
import Link from "next/link";
import MediaViewer from "./MediaViewer";
import { injectEmojis, renderCustomEmojis, CustomEmoji, useEmojiList } from "@/lib/emojis";
import { sanitizePost, sanitizeName } from "@/lib/sanitize";
import { rewriteLinks } from "@/lib/postContent";

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

export default function MiniPostCard({ post, notifType, notifLabel }: { post: PostData; notifType?: string; notifLabel?: React.ReactNode }) {
  const [isDark, setIsDark] = useState(false);
  const emojiList = useEmojiList();
  const [viewerIndex, setViewerIndex] = useState(-1);
  const mediaAttachments = useMemo(() => post.media_attachments || [], [post.media_attachments]);
  const postImages = useMemo(() => mediaAttachments.filter((m) => m.type !== "video"), [mediaAttachments]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsDark(document.body.classList.contains("dark-theme"));
  }, []);
  useEffect(() => {
    if (post._emojis) injectEmojis(post._emojis);
  }, [post._emojis]);
  const bg = notifType
    ? (isDark ? DARK_BG[notifType] : LIGHT_BG[notifType]) || "var(--bg-tertiary)"
    : "var(--bg-tertiary)";
  const mergedEmojiList = useMemo(() => {
    const postEmojis = post._emojis;
    if (!postEmojis || postEmojis.length === 0) return emojiList;
    // 같은 키워드 충돌 시 이 글의 _emojis(작성자 도메인 기준)를 우선한다.
    const seen = new Map<string, CustomEmoji>();
    for (const e of postEmojis) {
      if (e.keyword && e.url) seen.set(e.keyword, { ...e, category: "remote" });
    }
    for (const e of emojiList) {
      if (!seen.has(e.keyword)) seen.set(e.keyword, e);
    }
    return Array.from(seen.values());
  }, [emojiList, post._emojis]);
  const contentHtml = useMemo(() => {
    let html = post.content || "";
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    html = renderCustomEmojis(html, mergedEmojiList);
    return sanitizePost(rewriteLinks(html));
  }, [post.content, mergedEmojiList]);
  const makeUrl = (p: PostData): string => {
    if (p.number && p.author?.username) {
      return `/@${p.author.username}/${p.number}`;
    }
    if (p.id) {
      return `/post/${p.id}`;
    }
    return '#'; // 모든 조건에 해당 안 될 때의 기본 안전 경로
  };

  if (!post || !post.author) return null;
  return (<>
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
            <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.author.display_name || post.author.username, mergedEmojiList, 14)) }} />
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
        {mediaAttachments.length > 0 && (
          <div onClick={(e) => { e.preventDefault(); e.stopPropagation(); }} style={{ display: "grid", gridTemplateColumns: mediaAttachments.length <= 2 ? "1fr" : "1fr 1fr", gridAutoRows: "120px", gap: 2, marginTop: 6, borderRadius: 4, overflow: "hidden" }}>
            {mediaAttachments.slice(0, 4).map((m, i) => (
              m.type === "video" ? (
                <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden", background: "#000", borderRadius: 4 }}>
                  <video src={m.url} controls style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }} onClick={(e) => { e.preventDefault(); e.stopPropagation(); }} />
                </div>
              ) : (
                <img key={i} src={m.url} alt={m.alt || ""} style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000", borderRadius: 4, cursor: "pointer" }} onClick={(e) => { e.preventDefault(); e.stopPropagation(); const idx = postImages.indexOf(m); setViewerIndex(idx); }} />
              )
            ))}
          </div>
        )}
      </div>
    </Link>
    {viewerIndex >= 0 && postImages.length > 0 && (
      <MediaViewer
        media={postImages}
        index={viewerIndex}
        onIndexChange={setViewerIndex}
        onClose={() => setViewerIndex(-1)}
      />
    )}
  </>);
}
