"use client";
import { useEffect, useRef } from "react";
import PostForm from "./PostForm";

export default function SharePostModal({ url, title, authorName, description, tags, content, onClose, onDone }: { url: string; title?: string; authorName?: string; description?: string; tags?: string; content?: string; onClose: () => void; onDone?: () => void }) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const fullUrl = url.startsWith("http") ? url : window.location.origin + url;
  const initialContent = (() => {
    const seriesRegex = /^\/series\//;
    const episodeRegex = /\/episodes\//;
    const parts = [`「${title || url}」`];
    if (authorName) parts.push(`by ${authorName}`);
    if (description) parts.push(`\n${description}`);
    if (tags) parts.push(`\n#${tags.split(/[ ,]+/).filter(Boolean).join(" #")}`);
    if (content) parts.push(`\n${content}`)
    if (episodeRegex.test(url)) parts.push(`episode : ${fullUrl}`)
    else if (seriesRegex.test(url)) parts.push(`series : ${fullUrl}`)
    return parts.join("\n");
  })();

  const handleDone = async () => {
    if (onDone) onDone();
    onClose();
  };

  return (
    <div className="reply-modal-backdrop active" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>포스트로 공유</h3>
        <PostForm onDone={handleDone} initialContent={initialContent} shareUrl={fullUrl} />
      </div>
    </div>
  );
}
