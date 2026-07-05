"use client";
import { useEffect, useState, useCallback } from "react";
import PostForm from "./PostForm";

export default function KeyboardShortcuts() {
  const [showHelp, setShowHelp] = useState(false);
  const [showPostModal, setShowPostModal] = useState(false);

  const handleKey = useCallback((e: KeyboardEvent) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    const isEditing = tag === "input" || tag === "textarea" || tag === "select";

    if (e.key === "Escape") {
      if (isEditing) {
        (document.activeElement as HTMLElement)?.blur();
      }
      setShowHelp(false);
      setShowPostModal(false);
      return;
    }

    if (e.key === "?" && !isEditing) {
      e.preventDefault();
      setShowHelp((v) => !v);
      return;
    }

    if (e.key === "n" && !isEditing) {
      e.preventDefault();
      setShowPostModal(true);
      return;
    }

    if (e.key === "s" && !isEditing) {
      e.preventDefault();
      const search = document.querySelector<HTMLInputElement>(".sidebar-search-input");
      search?.focus();
      return;
    }

    if (e.key === "d" && !isEditing) {
      e.preventDefault();
      (window as any).__toggleTheme?.();
      window.dispatchEvent(new Event("themechange"));
      return;
    }
  }, []);

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <>
      <div
        className={`shortcut-help-backdrop ${showHelp ? "active" : ""}`}
        onClick={() => setShowHelp(false)}
      >
        <div className="shortcut-help" onClick={(e) => e.stopPropagation()}>
          <button className="shortcut-help-close" onClick={() => setShowHelp(false)}>×</button>
          <h3>키보드 단축키</h3>
          <dl>
            <dt>n</dt><dd>새 글 작성</dd>
            <dt>s</dt><dd>검색창</dd>
            <dt>d</dt><dd>테마 전환</dd>
            <dt>?</dt><dd>도움말</dd>
            <dt>Esc</dt><dd>입력 포커스 해제 / 모달 닫기</dd>
          </dl>
        </div>
      </div>

      {showPostModal && (
        <div className="reply-modal-backdrop active" onClick={() => setShowPostModal(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
            <button className="reply-modal-close" onClick={() => setShowPostModal(false)}>×</button>
            <h3>새 글 작성</h3>
            <PostForm onDone={() => setShowPostModal(false)} />
          </div>
        </div>
      )}
    </>
  );
}
