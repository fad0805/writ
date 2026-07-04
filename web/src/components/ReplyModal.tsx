"use client";
import { useEffect } from "react";
import { PostData } from "@/lib/api";
import PostForm from "./PostForm";

export default function ReplyModal({ post, onClose, onDone }: { post: PostData; onClose: () => void; onDone?: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>답글 작성</h3>
        <div className="reply-modal-original">
          <strong>{post.author.display_name} <span className="reply-modal-handle">@{post.author.username}</span></strong>
          <p className="reply-modal-content">{post.content}</p>
        </div>
        <PostForm parentId={post.id} placeholder="답글을 입력하세요..." onDone={onDone} />
      </div>
    </div>
  );
}
