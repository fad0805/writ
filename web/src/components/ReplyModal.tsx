"use client";
import { useEffect, useMemo } from "react";
import { PostData } from "@/lib/api";
import PostForm from "./PostForm";
import { useAuth } from "@/lib/auth";

const VIS_ORDER: Record<string, number> = { public: 0, home: 1, followers: 2, mention: 3 };

export default function ReplyModal({ post, onClose, onDone }: { post: PostData; onClose: () => void; onDone?: (newPost?: PostData) => void }) {
  const { user } = useAuth();
  const replyVis = useMemo(() => {
    const userVis = user?.default_visibility || "public";
    const parentVis = post.visibility || "public";
    return VIS_ORDER[userVis] >= VIS_ORDER[parentVis] ? userVis : parentVis;
  }, [user, post.visibility]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    const ta = document.querySelector<HTMLTextAreaElement>(".reply-modal textarea, .reply-modal .textarea-ta");
    setTimeout(() => {
      if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length; }
    }, 100);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const mentions = useMemo(() => {
    const set = new Set<string>();
    const matches = post.content.match(/@([a-zA-Z0-9_]+(?:@[a-zA-Z0-9.-]+)?)/g);
    if (matches) matches.forEach((m) => set.add(m));
    set.add(`@${post.author.username}`);
    if (user) set.delete(`@${user.username}`);
    return Array.from(set).join(" ") + (set.size > 0 ? " " : "");
  }, [post, user]);

  return (
    <div className="reply-modal-backdrop active" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>답글 작성</h3>
        <div className="reply-modal-original">
          <strong>{post.author.display_name} <span className="reply-modal-handle">@{post.author.username}</span></strong>
          <p className="reply-modal-content" dangerouslySetInnerHTML={{ __html: post.content.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<[^>]+\s+on\w+\s*=\s*[^>]*>/gi, '').replace(/<img[^>]*>/gi, '').replace(/\n/g, '<br>') }} />
        </div>
        <PostForm key={post.id} parentId={post.id} initialVisibility={replyVis} placeholder="답글을 입력하세요..." onDone={onDone} initialContent={mentions} />
      </div>
    </div>
  );
}
