"use client";
import { PostData } from "@/lib/api";
import { CustomEmoji, renderCustomEmojis } from "@/lib/emojis";
import { sanitizeName } from "@/lib/sanitize";
import Link from "next/link";
import Avatar from "./Avatar";
import Icon from "./Icon";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

export default function PostHeader({ post, mergedEmojiList, timeStr, postHref }: {
  post: PostData;
  mergedEmojiList: CustomEmoji[];
  timeStr: string;
  postHref: string;
}) {
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
        {timeStr ? <Link href={postHref} className="no-underline" style={{ color: "inherit" }}>{timeStr}</Link> : null}
      </span>
    </div>
  );
}
