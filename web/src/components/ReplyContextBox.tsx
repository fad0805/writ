"use client";
import { PostData } from "@/lib/api";
import { CustomEmoji, renderCustomEmojis } from "@/lib/emojis";
import { sanitizeName, sanitizePost } from "@/lib/sanitize";
import { rewriteLinks } from "@/lib/postContent";
import Link from "next/link";

export default function ReplyContextBox({ post, mergedEmojiList, validMentions }: {
  post: PostData;
  mergedEmojiList: CustomEmoji[];
  validMentions: Set<string>;
}) {
  if (!post.reply_context) return null;
  const rc = post.reply_context;
  return (
    <Link href={rc.number ? `/@${rc.author.username}/${rc.number}` : `/post/${rc.id}`} className={`reply-context${rc.visibility === "mention" ? " mention-context" : ""}`} onClick={(e) => e.stopPropagation()}>
      <span className="reply-context-label">답글 대상</span>
      <strong dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(rc.author.display_name || rc.author.username, mergedEmojiList, 14)) }} />
      <span>@{rc.author.username}</span>
      <p dangerouslySetInnerHTML={{ __html: (() => {
        const hasCw = !!(rc as any).summary || !!(rc as any).is_sensitive;
        if (hasCw) {
          const cwLabel = (rc as any).summary || "내용 숨김";
          return `<span style="opacity:0.5;font-size:0.9em">${cwLabel}</span>`;
        }
        const rawText = (rc.content || "");
        const text = rawText.slice(0, 200);
        let html = text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/\n/g, '<br>');
        html = renderCustomEmojis(html, mergedEmojiList);
        html = rewriteLinks(html, validMentions);
        if (rawText.length > 200) html += "...";
        return sanitizePost(html);
      })() }} />
    </Link>
  );
}
