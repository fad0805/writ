"use client";
import { useState, useEffect } from "react";
import { PostData, api } from "@/lib/api";
import EmojiPicker from "./EmojiPicker";

export default function EditModal({ post, onClose, onDone }: { post: PostData; onClose: () => void; onDone?: (updated?: PostData) => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const [content, setContent] = useState(() => {
    if (typeof window === "undefined") return post.content;
    const div = document.createElement("div");
    div.innerHTML = post.content;

    // 모든 <a> 태그를 대상으로 복구 작업 시작
    const links = div.querySelectorAll("a");
    links.forEach((link) => {
      const href = link.getAttribute("href") || "";
      // 1️⃣ 해시태그 검사: 클래스명에 hashtag가 있거나, 주소에 /explore가 포함된 경우
      const isHashtag = link.classList.contains("hashtag") || href.includes("/explore");

      const isMention = link.classList.contains("mention");

      if (isHashtag) {
        // 해시태그는 주소로 바꾸지 않고 원래 텍스트(#ActivityPub)를 그대로 둡니다.
        if (!link.textContent?.startsWith("#")) {
          const match = href.match(/[?&]q=%23([^&]+)/);
          if (match) link.textContent = `#${decodeURIComponent(match[1])}`;
        }
      } else if (isMention && href.startsWith("/@")) {
        // 멘션: href의Leading '/'를 제거하여 @handle@domain 형태로 복원
        link.textContent = href.substring(1);
      } else if (href) {
        // 2️⃣ [일반 URL + 시리즈/에피소드 주소 일괄 복구]
        // 해시태그가 아닌 모든 <a> 태그는 말줄임표(...)를 지우고 href의 진짜 원본 주소로 채워 넣습니다.
        link.textContent = href;
      }
    });

    // <br> 태그를 줄바꿈(\n)으로 치환
    const htmlWithNewlines = div.innerHTML.replace(/<br\s*\/?>/gi, "\n");
    div.innerHTML = htmlWithNewlines;

    // 최종적으로 태그를 다 벗겨낸 온전한 텍스트를 반환합니다.
    return div.textContent || div.innerText || "";
  });

  const [summary, setSummary] = useState(post.summary);
  const [submitting, setSubmitting] = useState(false);
  const forceCw = post.summary?.startsWith("[관리자 강제] ");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim() || submitting) return;
    if (forceCw) { alert("관리자가 강제한 CW는 수정할 수 없습니다"); return; }
    setSubmitting(true);
    try {
      const updatedPost = await api.editPost(post.id, { content, summary });
      if (onDone) onDone(updatedPost);
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
          {/* 원문 보기 영역도 유저가 알아볼 수 있게 가볍게 텍스트만 출력되게 하거나 HTML 프리뷰 처리를 할 수 있습니다 */}
          <p className="edit-modal-original-text" dangerouslySetInnerHTML={{ __html: post.content }} />
        </div>
        <form onSubmit={handleSubmit}>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={10} // 글쓰기 편하게 rows를 조금 늘려주셔도 좋아요!
            placeholder="내용을 수정하세요..."
            required
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { (e.target as HTMLElement).closest('form')?.requestSubmit(); } }}
          />
          <input
            type="text"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder={forceCw ? "관리자가 강제한 CW입니다" : "CW (선택사항)"}
            className="cw-input"
            disabled={forceCw}
            style={forceCw ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
          />
          <div className="edit-modal-footer edit-modal-footer-flex">
            <EmojiPicker onEmoji={(e) => setContent(content + e + " ")} />
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
