"use client";
import { PostData } from "@/lib/api";
import ReplyModal from "./ReplyModal";
import PostForm from "./PostForm";

export default function RewriteModal({ post, initialContent, initialSummary, initialVisibility, initialMedia, onClose, onDone }: {
  post: PostData;
  initialContent?: string;
  initialSummary: string;
  initialVisibility?: string;
  initialMedia: { url: string; type: string; alt?: string }[];
  onClose: () => void;
  onDone?: () => void;
}) {
  if (post.reply_context) {
    return (
      <ReplyModal post={{
        id: post.reply_context.id,
        number: post.reply_context.number,
        content: post.reply_context.content,
        author: post.reply_context.author,
        visibility: post.reply_context.visibility,
        summary: null,
        created_at: null,
        ap_id: "",
        likes_count: 0,
        boosts_count: 0,
        replies_count: 0,
        liked: false,
        boosted: false,
        bookmarked: false,
        is_mine: false,
        reply_context: null,
        media_attachments: [],
      } as any} initialContent={initialContent} initialSummary={initialSummary} initialMedia={initialMedia} onClose={onClose} onDone={() => { onClose(); onDone?.(); }} />
    );
  }
  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal modal-form" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>지우고 다시 쓰기</h3>
        <PostForm onDone={onClose} initialContent={initialContent} initialSummary={initialSummary} initialVisibility={initialVisibility} initialMedia={initialMedia} />
      </div>
    </div>
  );
}
