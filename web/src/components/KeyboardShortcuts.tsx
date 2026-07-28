"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import NewPostModal from "./NewPostModal";

export default function KeyboardShortcuts() {
  const router = useRouter();
  const { user } = useAuth();
  const [showHelp, setShowHelp] = useState(false);
  const [showPostModal, setShowPostModal] = useState(false);
  const gPendingRef = useRef(false);
  const gTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleKey = useCallback((e: KeyboardEvent) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    const isEditing = tag === "input" || tag === "textarea" || tag === "select" || document.activeElement?.closest(".ProseMirror, .episode-editor") != null;

    if (e.key === "Backspace" && !isEditing && !e.repeat) {
      e.preventDefault();
      router.back();
      return;
    }

    if (e.key === "Escape") {
      if (isEditing) (document.activeElement as HTMLElement)?.blur();
      setShowHelp(false);
      setShowPostModal(false);
      gPendingRef.current = false;
      return;
    }

    if (e.key === "?" && !isEditing) {
      e.preventDefault();
      setShowHelp((v) => !v);
      return;
    }

    // g-prefix sequences
    if (gPendingRef.current) {
      gPendingRef.current = false;
      clearTimeout(gTimerRef.current);
      if (e.key === "t") { e.preventDefault(); router.push("/timeline/federated"); return; }
      if (e.key === "l") { e.preventDefault(); router.push("/timeline/local"); return; }
      if (e.key === "s") { e.preventDefault(); router.push("/timeline/social"); return; }
      if (e.key === "n") { e.preventDefault(); router.push("/notifications"); return; }
      if (e.key === "h") { e.preventDefault(); router.push("/timeline/home"); return; }
      return;
    }

    if (e.key === "g" && !isEditing) {
      e.preventDefault();
      gPendingRef.current = true;
      gTimerRef.current = setTimeout(() => { gPendingRef.current = false; }, 800);
      return;
    }

      if (e.key === "n" && !isEditing && user) {
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

    if (e.key === "d" && !isEditing && !document.querySelector(".post-card.selected")) {
      e.preventDefault();
      (window as any).__toggleTheme?.();
      window.dispatchEvent(new Event("themechange"));
      return;
    }
  }, [router, user]);

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <>
      <div className={`shortcut-help-backdrop ${showHelp ? "active" : ""}`} onClick={() => setShowHelp(false)}>
        <div className="shortcut-help" onClick={(e) => e.stopPropagation()}>
          <button className="shortcut-help-close" onClick={() => setShowHelp(false)}>×</button>
          <h3>키보드 단축키</h3>
          <dl>
            <dt>g h</dt><dd>홈 타임라인</dd>
            <dt>g t</dt><dd>연합 타임라인</dd>
            <dt>g n</dt><dd>알림</dd>
            <dt>n</dt><dd>새 글 작성</dd>
            <dt>s</dt><dd>검색창</dd>
            <dt>d</dt><dd>테마 전환</dd>
            <dt>?</dt><dd>도움말</dd>
            <dt>Esc</dt><dd>입력 포커스 해제</dd>
          </dl>
        </div>
      </div>

      {showPostModal && <NewPostModal onClose={() => setShowPostModal(false)} />}
    </>
  );
}
