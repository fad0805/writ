"use client";
import { useEffect, useMemo, useRef } from "react";
import { PostData } from "@/lib/api";
import PostForm from "./PostForm";
import { useAuth } from "@/lib/auth";
import { sanitizePost } from "@/lib/sanitize";

const VIS_ORDER: Record<string, number> = { public: 0, home: 1, followers: 2, mention: 3 };

export default function ReplyModal({ post, onClose, onDone, initialContent }: { post: PostData; onClose: () => void; onDone?: (newPost?: PostData) => void; initialContent?: string }) {
  const { user } = useAuth();
  const replyVis = useMemo(() => {
    const userVis = user?.default_visibility || "public";
    const parentVis = post.visibility || "public";
    return VIS_ORDER[userVis] >= VIS_ORDER[parentVis] ? userVis : parentVis;
  }, [user, post.visibility]);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", handler);
    const ta = document.querySelector<HTMLTextAreaElement>(".reply-modal textarea, .reply-modal .textarea-ta");
    setTimeout(() => {
      if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length; }
    }, 100);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const mentions = useMemo(() => {
    const set = new Set<string>();
    set.add(`@${post.author.username}`);
    const text = (() => {
      try {
        const doc = new DOMParser().parseFromString(post.content || "", "text/html");
        const parts: string[] = [];
        const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
        let node: Node | null;
        while ((node = walker.nextNode())) {
          const a = node.parentElement?.closest("a");
          if (a && !a.classList.contains("mention")) continue;
          parts.push(node.textContent || "");
        }
        return parts.join(" ");
      } catch {
        return (post.content || "").replace(/<[^>]*>/g, "");
      }
    })().replace(/https?:\/\/[^\s<>]+/gi, "");
    const matches = text.match(/@([a-zA-Z0-9_]+(?:@[a-zA-Z0-9.-]+)?)/g);
    if (matches) matches.forEach((m) => set.add(m));
    if (user) {
      const uname = user.username;
      for (const m of Array.from(set)) {
        const parts = (m.startsWith("@") ? m.slice(1) : m).split("@");
        const mName = parts[0];
        const mDomain = parts[1] || "";
        if (mName === uname && !mDomain) set.delete(m);
      }
    }
    const sorted = Array.from(set);
    const parentIdx = sorted.indexOf(`@${post.author.username}`);
    if (parentIdx > 0) {
      sorted.splice(parentIdx, 1);
      sorted.unshift(`@${post.author.username}`);
    }
    return sorted.join(" ") + (sorted.length > 0 ? " " : "");
  }, [post, user]);

  return (
    <div className="reply-modal-backdrop active" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>답글 작성</h3>
        <div className="reply-modal-original">
          <strong>{post.author.display_name} <span className="reply-modal-handle">@{post.author.username}</span></strong>
          <p className="reply-modal-content" dangerouslySetInnerHTML={{ __html: sanitizePost(post.content.replace(/\n/g, '<br>')) }} />
        </div>
        <PostForm key={post.boost_of_id || post.id} parentId={post.boost_of_id || post.id} initialVisibility={replyVis} placeholder="답글을 입력하세요..." onDone={onDone} initialContent={initialContent || mentions} parentSummary={post.summary} />
      </div>
    </div>
  );
}
