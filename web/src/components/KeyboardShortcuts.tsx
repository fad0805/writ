"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import NewPostModal from "./NewPostModal";

export default function KeyboardShortcuts() {
  const router = useRouter();
  const { user } = useAuth();
  const [showHelp, setShowHelp] = useState(false);
  const [helpTab, setHelpTab] = useState<"general" | "timeline">("general");
  const [showPostModal, setShowPostModal] = useState(false);
  const gPendingRef = useRef(false);
  const gTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleKey = useCallback((e: KeyboardEvent) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    const isEditing = tag === "input" || tag === "textarea" || tag === "select" || document.activeElement?.closest(".ProseMirror, .episode-editor") != null;

    if (e.key === "Backspace" && !isEditing && !e.repeat) {
      if (document.querySelector(".modal-overlay")) return;
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
      const next = !showHelp;
      setShowHelp(next);
      if (next) setHelpTab("general");
      return;
    }

    if (showHelp && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      e.preventDefault();
      setHelpTab(e.key === "ArrowRight" ? "timeline" : "general");
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

    if (e.key === "n" && user && !isEditing) {
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
      (window as unknown as { __toggleTheme?: () => void }).__toggleTheme?.();
      window.dispatchEvent(new Event("themechange"));
      return;
    }
  }, [router, user, showHelp]);

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
          <div className="shortcut-help-tabs">
            <button type="button" className={helpTab === "general" ? "active" : ""} onClick={() => setHelpTab("general")}>일반</button>
            <button type="button" className={helpTab === "timeline" ? "active" : ""} onClick={() => setHelpTab("timeline")}>타임라인</button>
          </div>
          {helpTab === "general" ? (
          <dl>
            <dt>g h</dt><dd>홈 타임라인</dd>
            <dt>g s</dt><dd>소셜 타임라인</dd>
            <dt>g l</dt><dd>로컬 타임라인</dd>
            <dt>g t</dt><dd>연합 타임라인</dd>
            <dt>g n</dt><dd>알림</dd>
            <dt>n</dt><dd>새 글 작성</dd>
            <dt>s</dt><dd>검색창</dd>
            <dt>d</dt><dd>테마 전환</dd>
            <dt>?</dt><dd>단축키 도움말</dd>
            <dt>Esc</dt><dd>입력 포커스 해제 / 닫기</dd>
            <dt>Backspace</dt><dd>뒤로 가기</dd>
          </dl>
          ) : (
          <dl>
            <dt>j / k</dt><dd>다음 / 이전 포스트 선택</dd>
            <dt>Enter</dt><dd>포스트 열기</dd>
            <dt>f</dt><dd>좋아요</dd>
            <dt>b</dt><dd>부스트</dd>
            <dt>d</dt><dd>북마크</dd>
            <dt>r</dt><dd>답글</dd>
            <dt>x</dt><dd>CW 펼치기</dd>
            <dt>e</dt><dd>미디어 확대</dd>
            <dt>.</dt><dd>타임라인 맨 위로 / 선택한 포스트 최상단으로</dd>
            <dt>h / l</dt><dd>이전 / 다음 타임라인 탭</dd>
            <dt>Esc</dt><dd>선택 해제</dd>
          </dl>
          )}
        </div>
      </div>

      {showPostModal && <NewPostModal onClose={() => setShowPostModal(false)} />}
    </>
  );
}
