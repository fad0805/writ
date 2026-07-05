"use client";
import { useEffect, useMemo } from "react";
import { PostData } from "@/lib/api";
import PostForm from "./PostForm";
import { useAuth } from "@/lib/auth";

export default function ReplyModal({ post, onClose, onDone }: { post: PostData; onClose: () => void; onDone?: () => void }) {
  const { user } = useAuth();
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const mentions = useMemo(() => {
    const set = new Set<string>();
    const matches = post.content.match(/@(\w+)/g);
    if (matches) matches.forEach((m) => set.add(m));
    set.add(`@${post.author.username}`);
    if (user) set.delete(`@${user.username}`);
    return Array.from(set).join(" ") + (set.size > 0 ? " " : "");
  }, [post, user]);

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>답글 작성</h3>
        <div className="reply-modal-original">
          <strong>{post.author.display_name} <span className="reply-modal-handle">@{post.author.username}</span></strong>
          <p className="reply-modal-content">{post.content}</p>
        </div>
        <PostForm key={post.id} parentId={post.id} placeholder="답글을 입력하세요..." onDone={onDone} initialContent={mentions} />
      </div>
    </div>
  );
}
