"use client";
import { useRef, useEffect, ReactNode } from "react";
import Loading from "./Loading";

export default function InfiniteScroll({
  hasMore, loadingMore, loadMore, children,
}: {
  hasMore: boolean; loadingMore: boolean; loadMore: () => void; children: ReactNode;
}) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  const loadingRef = useRef(loadingMore);
  loadingRef.current = loadingMore;

  useEffect(() => {
    if (!hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const scrollRoot = document.querySelector(".main-content");
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !loadingRef.current && hasMore) {
        loadingRef.current = true;
        loadMoreRef.current();
      }
    }, { root: scrollRoot, rootMargin: "200px" });
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loadingMore]);

  return (
    <>
      {children}
      <div ref={sentinelRef} className="sentinel" />
      {loadingMore && <Loading text="불러오는 중..." />}
    </>
  );
}
