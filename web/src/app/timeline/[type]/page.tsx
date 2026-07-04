"use client";
import { useParams } from "next/navigation";
import { useState, useEffect, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import PostForm from "@/components/PostForm";
import Icon from "@/components/Icon";
import Link from "next/link";

const LIMIT = 10;
const LOAD_MORE = 5;

const TABS = [
  { key: "home", label: "홈", icon: "home" },
  { key: "social", label: "소셜", icon: "users" },
  { key: "local", label: "로컬", icon: "buildings" },
  { key: "federated", label: "연합", icon: "globe" },
];

export default function TimelinePage() {
  const params = useParams();
  const tlType = (params.type as string) || "home";
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState("");
  const sentinelRef = useRef<HTMLDivElement>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.timeline(tlType, LIMIT, 0);
      setPosts(data.posts);
      setHasMore(data.has_more);
    } catch (e: any) {
      setError(e.message || "불러오기 실패");
    }
    setLoading(false);
  };

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await api.timeline(tlType, LOAD_MORE, posts.length);
      setPosts((prev) => [...prev, ...data.posts]);
      setHasMore(data.has_more);
    } catch {}
    setLoadingMore(false);
  }, [tlType, posts.length, loadingMore, hasMore]);

  useEffect(() => { load(); }, [tlType]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  return (
    <>
      <div className="post-form">
        <PostForm />
      </div>
      <div className="timeline-tabs">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={`/timeline/${t.key}`}
            className={t.key === tlType ? "active" : ""}
          >
            <Icon name={t.icon} /> {t.label}
          </Link>
        ))}
      </div>
      <div className="feed">
        {loading ? (
          <p className="empty-state">로딩 중...</p>
        ) : error ? (
          <p className="empty-state">오류: {error}</p>
        ) : posts.length === 0 ? (
          <p className="empty-state">표시할 글이 없습니다.</p>
        ) : (
          <>
            {posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
            <div ref={sentinelRef} className="sentinel" />
            {loadingMore && <p className="empty-state">불러오는 중...</p>}
          </>
        )}
      </div>
    </>
  );
}
