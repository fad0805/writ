"use client";
import { useEffect } from "react";
import PostForm from "./PostForm";

export default function SharePostModal({ url, title, onClose, onDone }: { url: string; title?: string; onClose: () => void; onDone?: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const fullUrl = url.startsWith("http") ? url : window.location.origin + url;
  const initialContent = `${title || ""} ${fullUrl}`;

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>포스트로 공유</h3>
        <PostForm onDone={() => { if (onDone) onDone(); onClose(); }} initialContent={initialContent} />
      </div>
    </div>
  );
}
