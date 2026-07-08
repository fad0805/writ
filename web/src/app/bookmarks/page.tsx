"use client";
import { useEffect, useState, useCallback } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import InfiniteScroll from "@/components/InfiniteScroll";
import Icon from "@/components/Icon";

export default function BookmarksPage() {
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(20);

  const load = useCallback(() => {
    setLoading(true);
    api.getBookmarks(20, 0)
      .then((d) => { setPosts(d.posts); setHasMore(d.has_more); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const d = await api.getBookmarks(10, offset);
      setPosts((prev) => [...prev, ...d.posts]);
      setHasMore(d.has_more);
      setOffset((prev) => prev + 10);
    } catch {}
    setLoadingMore(false);
  }, [offset, hasMore, loadingMore]);

  return (
    <>
      <h2><Icon name="bookmark" /> 북마크</h2>
      {loading ? <p className="empty-state">로딩 중...</p> : (
        posts.length === 0 ? <p className="empty-state">북마크한 게시글이 없습니다.</p> : (
          <InfiniteScroll hasMore={hasMore} loadingMore={loadingMore} loadMore={loadMore}>
            {posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
          </InfiniteScroll>
        )
      )}
    </>
  );
}
