"use client";
import { useEffect } from "react";
import PostForm from "./PostForm";

export default function MentionModal({ username, onClose, onDone }: { username: string; onClose: () => void; onDone?: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>멘션 보내기</h3>
        <PostForm onDone={onDone} initialContent={`@${username} `} placeholder={`@${username}에게 멘션 보내기...`} />
      </div>
    </div>
  );
}
