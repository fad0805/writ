"use client";
import { useEffect } from "react";
import PostForm from "./PostForm";
import { useAuth } from "@/lib/auth";

export default function NewPostModal({ onClose }: { onClose: () => void }) {
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    const id = setInterval(() => {
      const ta = document.querySelector<HTMLTextAreaElement>(".reply-modal .textarea-ta");
      if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length; clearInterval(id); }
    }, 50);
    return () => { window.removeEventListener("keydown", handler); clearInterval(id); };
  }, [onClose, loading]);

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal modal-form">
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>새 글 작성</h3>
        {loading ? <p className="empty-small text-center">로딩 중...</p> : <PostForm onDone={onClose} initialVisibility={user?.default_visibility} />}
      </div>
    </div>
  );
}
