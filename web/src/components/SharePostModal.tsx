"use client";
import { useEffect } from "react";
import PostForm from "./PostForm";

export default function SharePostModal({ url, title, authorName, description, tags, content, onClose, onDone }: { url: string; title?: string; authorName?: string; description?: string; tags?: string; content?: string; onClose: () => void; onDone?: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const fullUrl = url.startsWith("http") ? url : window.location.origin + url;
  const initialContent = content || (() => {
    const parts = [`「${title || url}」`];
    if (authorName) parts.push(`by ${authorName}`);
    if (description) parts.push(`\n${description}`);
    if (tags) parts.push(`\n#${tags.split(/[ ,]+/).filter(Boolean).join(" #")}`);
    return parts.join("\n");
  })();

  const handleDone = async () => {
    if (onDone) onDone();
    onClose();
  };

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>포스트로 공유</h3>
        <PostForm onDone={handleDone} initialContent={initialContent} shareUrl={fullUrl} />
      </div>
    </div>
  );
}
