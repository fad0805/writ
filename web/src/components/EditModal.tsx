"use client";
import { useState, useEffect } from "react";
import { PostData, api } from "@/lib/api";
import EmojiPicker from "./EmojiPicker";

export default function EditModal({ post, onClose, onDone }: { post: PostData; onClose: () => void; onDone?: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  const [content, setContent] = useState(() => post.content.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, ""));
  const [summary, setSummary] = useState(post.summary);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim() || submitting) return;
    setSubmitting(true);
    try {
      await api.editPost(post.id, { content, summary });
      if (onDone) onDone();
    } catch (err: any) { alert(err.message); }
    setSubmitting(false);
  };

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>글 수정</h3>
        <div className="reply-modal-original">
          <strong>수정 전 원문</strong>
          <p className="edit-modal-original-text">{post.content}</p>
        </div>
        <form onSubmit={handleSubmit}>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            placeholder="내용을 수정하세요..."
            required
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { (e.target as HTMLElement).closest('form')?.requestSubmit(); } }}
          />
          <input
            type="text"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="CW (선택사항)"
            className="cw-input"
          />
          <div className="edit-modal-footer edit-modal-footer-flex">
            <EmojiPicker onEmoji={(e) => setContent(content + e)} />
            <div className="flex-spacer" />
            <button type="submit" disabled={submitting || !content.trim()} className="btn btn-primary">
              {submitting ? "..." : "수정"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
