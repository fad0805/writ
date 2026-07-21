"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import InfiniteScroll from "@/components/InfiniteScroll";
import Icon from "@/components/Icon";

const FILTERS = [
  { value: "bookmarks", label: "북마크", icon: "bookmark" as const },
  { value: "favorites", label: "즐겨찾기", icon: "star" as const },
];

export default function MyArchivePage() {
  const [filter, setFilter] = useState("bookmarks");
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(20);
  const touchStartX = useRef(0);

  const load = useCallback(() => {
    setLoading(true);
    const fetcher = filter === "bookmarks" ? api.getBookmarks(20, 0) : api.getFavorites(20, 0);
    fetcher.then((d) => { setPosts(d.posts); setHasMore(d.has_more); setLoading(false); }).catch(() => setLoading(false));
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const fetcher = filter === "bookmarks" ? api.getBookmarks(10, offset) : api.getFavorites(5, offset);
      const d = await fetcher;
      setPosts((prev) => [...prev, ...d.posts]);
      setHasMore(d.has_more);
      setOffset((prev) => prev + (filter === "bookmarks" ? 10 : 5));
    } catch {}
    setLoadingMore(false);
  }, [filter, offset, hasMore, loadingMore]);

  useEffect(() => {
    const h = (e: TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
    document.addEventListener("touchstart", h, { passive: true });
    return () => document.removeEventListener("touchstart", h);
  }, []);

  useEffect(() => {
    const h = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 100) {
        const idx = FILTERS.findIndex((f) => f.value === filter);
        if (dx > 0 && idx > 0) setFilter(FILTERS[idx - 1].value);
        else if (dx < 0 && idx < FILTERS.length - 1) setFilter(FILTERS[idx + 1].value);
      }
    };
    document.addEventListener("touchend", h, { passive: true });
    return () => document.removeEventListener("touchend", h);
  }, [filter]);

  return (
    <div style={{ padding: "0 8px" }}>
      <h2><Icon name="archive" /> 내 보관함</h2>
      <div className="notif-tabs" style={{ marginBottom: 16 }}>
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className={`notif-tab${filter === f.value ? " active" : ""}`}
            onClick={() => { setFilter(f.value); setOffset(20); }}
          >
            <Icon name={f.icon} size={14} /> {f.label}
          </button>
        ))}
      </div>
      {loading ? <p className="empty-state">로딩 중...</p> : (
        posts.length === 0 ? (
          <p className="empty-state">{filter === "bookmarks" ? "북마크한 게시글이 없습니다." : "즐겨찾기한 게시글이 없습니다."}</p>
        ) : (
          <InfiniteScroll hasMore={hasMore} loadingMore={loadingMore} loadMore={loadMore}>
            {posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
          </InfiniteScroll>
        )
      )}
    </div>
  );
}
