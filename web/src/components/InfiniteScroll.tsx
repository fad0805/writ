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
    if (loadingRef.current || !hasMoreRef.current) {
      console.log("[InfiniteScroll] skip:", { loading: loadingRef.current, hasMore: hasMoreRef.current });
      return;
    }
    const el = document.querySelector(".main-content");
    if (!el) {
      console.log("[InfiniteScroll] no .main-content found");
      return;
    }
    const { scrollTop, scrollHeight, clientHeight } = el;
    const distance = scrollHeight - scrollTop - clientHeight;
    console.log("[InfiniteScroll] scroll check:", { scrollTop, scrollHeight, clientHeight, distance, threshold: 400, near: distance < 400 });
    if (distance < 400) {
      loadingRef.current = true;
      console.log("[InfiniteScroll] → loadMore triggered");
      loadMoreRef.current();
    }
  }, []);

  useEffect(() => {
    const el = document.querySelector(".main-content");
    if (!el) {
      console.log("[InfiniteScroll] no .main-content for scroll listener");
      return;
    }
    console.log("[InfiniteScroll] scroll listener attached to .main-content");
    el.addEventListener("scroll", checkNearBottom, { passive: true });
    return () => el.removeEventListener("scroll", checkNearBottom);
  }, [checkNearBottom]);

  useEffect(() => {
    console.log("[InfiniteScroll] post-load recheck:", { loadingMore, hasMore });
    if (!loadingMore && hasMore) checkNearBottom();
  }, [loadingMore, hasMore, checkNearBottom]);

  return (
    <>
      {children}
      {loadingMore && <Loading text="불러오는 중..." />}
    </>
  );
}
