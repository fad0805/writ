"use client";
import { useRef, useEffect, useCallback, ReactNode } from "react";
import Loading from "./Loading";

export default function InfiniteScroll({
  hasMore, loadingMore, loadMore, children,
}: {
  hasMore: boolean; loadingMore: boolean; loadMore: () => void; children: ReactNode;
}) {
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  const hasMoreRef = useRef(hasMore);
  hasMoreRef.current = hasMore;
  const loadingRef = useRef(loadingMore);
  loadingRef.current = loadingMore;

  const checkNearBottom = useCallback(() => {
    if (loadingRef.current || !hasMoreRef.current) return;
    const el = document.querySelector(".main-content");
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    if (scrollHeight - scrollTop - clientHeight < 400) {
      loadingRef.current = true;
      loadMoreRef.current();
    }
  }, []);

  useEffect(() => {
    let el: HTMLElement | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    const attach = () => {
      el = document.querySelector(".main-content");
      if (el) {
        el.addEventListener("scroll", checkNearBottom, { passive: true });
        if (timer) { clearInterval(timer); timer = null; }
      }
    };
    attach();
    if (!el) timer = setInterval(attach, 500);
    return () => {
      if (timer) clearInterval(timer);
      el?.removeEventListener("scroll", checkNearBottom);
    };
  }, [checkNearBottom]);

  useEffect(() => {
    if (!loadingMore && hasMore) checkNearBottom();
  }, [loadingMore, hasMore, checkNearBottom]);

  return (
    <>
      {children}
      {loadingMore && <Loading text="불러오는 중..." />}
    </>
  );
}
