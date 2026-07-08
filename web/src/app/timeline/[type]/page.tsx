"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import PostCard from "@/components/PostCard";
import PostForm from "@/components/PostForm";
import ReplyModal from "@/components/ReplyModal";
import InfiniteScroll from "@/components/InfiniteScroll";
import Icon from "@/components/Icon";
import Link from "next/link";

const LIMIT = 20;
const LOAD_MORE = 10;

const TABS = [
  { key: "home", label: "홈", icon: "home" },
  { key: "social", label: "소셜", icon: "users" },
  { key: "local", label: "로컬", icon: "buildings" },
  { key: "federated", label: "연합", icon: "globe" },
];

export default function TimelinePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const tlType = (params.type as string) || "home";
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [rawOffset, setRawOffset] = useState(0);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [replyPost, setReplyPost] = useState<PostData | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const postsRef = useRef(posts);
  postsRef.current = posts;
  const selectedIdxRef = useRef(selectedIdx);
  selectedIdxRef.current = selectedIdx;
  const tabCache = useRef<Record<string, { posts: PostData[]; hasMore: boolean; rawOffset: number }>>({});
  const prevTlRef = useRef(tlType);

  useEffect(() => {
    if (prevTlRef.current !== tlType) {
      tabCache.current[prevTlRef.current] = { posts, hasMore, rawOffset };
      prevTlRef.current = tlType;
    }
    const saved = tabCache.current[tlType];
    if (saved) {
      setPosts(saved.posts);
      setHasMore(saved.hasMore);
      setRawOffset(saved.rawOffset);
      setLoading(false);
      return;
    }
    load();
  }, [tlType]);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.timeline(tlType, LIMIT, 0);
      setPosts(data.posts);
      setHasMore(data.has_more);
      setRawOffset(LIMIT);
      tabCache.current[tlType] = { posts: data.posts, hasMore: data.has_more, rawOffset: LIMIT };
    } catch (e: any) {
      setError(e.message || "불러오기 실패");
    }
    setLoading(false);
  };

  useEffect(() => {
    if (refreshKey === 0) return;
    tabCache.current[tlType] = { posts, hasMore, rawOffset };
    load();
  }, [refreshKey]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener("followchange", handler);
    return () => window.removeEventListener("followchange", handler);
  }, [tlType]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await api.timeline(tlType, LOAD_MORE, rawOffset);
      setPosts((prev) => {
        const ids = new Set(prev.map((p) => p.id));
        const newPosts = data.posts.filter((p: any) => !ids.has(p.id));
        const total = prev.length + newPosts.length;
        if (total >= 500) setHasMore(false);
        return [...prev, ...newPosts];
      });
      setHasMore(data.has_more);
      setRawOffset((prev) => prev + LOAD_MORE);
    } catch {}
    setLoadingMore(false);
  }, [tlType, rawOffset, hasMore, loadingMore]);

  useEffect(() => { if (!authLoading && !user) router.replace("/"); }, [authLoading, user, router]);

  useEffect(() => {
    const handler = (e: FocusEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA") setSelectedIdx(-1);
    };
    document.addEventListener("focusin", handler);
    return () => document.removeEventListener("focusin", handler);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const selIdx = selectedIdxRef.current;
      const currentPosts = postsRef.current;
      if (e.key === "Escape" && selIdx >= 0) {
        e.preventDefault();
        setSelectedIdx(-1);
        return;
      }
      const tabs = ["home", "social", "local", "federated"];
      const currentTabIdx = tabs.indexOf(tlType);
      if (e.key === "h" && currentTabIdx > 0) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${tabs[currentTabIdx - 1]}`);
        return;
      }
      if (e.key === "l" && currentTabIdx < tabs.length - 1) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${tabs[currentTabIdx + 1]}`);
        return;
      }
      if (e.key === "j") {
        e.preventDefault();
        setSelectedIdx((prev) => {
          const next = prev < 0 ? 0 : Math.min(prev + 1, currentPosts.length - 1);
          cardRefs.current[next]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          return next;
        });
        return;
      }
      if (e.key === "k") {
        e.preventDefault();
        setSelectedIdx((prev) => {
          const next = Math.max(prev - 1, 0);
          cardRefs.current[next]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          return next;
        });
        return;
      }
      if (selIdx >= 0 && currentPosts[selIdx]) {
        const sp = currentPosts[selIdx];
        if (e.key === "f") { e.preventDefault(); (sp.liked ? api.unlike(sp.id) : api.like(sp.id)).then(() => load()).catch(() => {}); return; }
        if (e.key === "d") { e.preventDefault(); (sp.bookmarked ? api.unbookmark(sp.id) : api.bookmark(sp.id)).then(() => load()).catch(() => {}); return; }
        if (e.key === "b") { e.preventDefault(); (sp.boosted ? api.unboost(sp.id) : api.boost(sp.id)).then(() => load()).catch(() => {}); return; }
        if (e.key === "r") { e.preventDefault(); api.getPost(sp.id).then((d) => setReplyPost(d)).catch(() => {}); return; }
        if (e.key === "Enter") { e.preventDefault(); router.push(sp.number ? `/@${sp.author.username}/${sp.number}` : `/post/${sp.id}`); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tlType]);

  useEffect(() => {
    let es: EventSource | null = null;
    try { es = new EventSource(`/api/timeline/stream?type=${tlType}`); } catch { return; }
    es.onmessage = (event) => {
      try {
        const newPost = JSON.parse(event.data);
        setPosts((prev) => {
          if (prev.some((p) => p.id === newPost.id)) return prev;
          return [newPost, ...prev];
        });
      } catch {}
    };
    es.onerror = () => {};
    return () => { es?.close(); };
  }, [tlType]);

  useEffect(() => {
    const interval = setInterval(() => {
      api.timeline(tlType, LIMIT, 0).then((data) => {
        setPosts((prev) => {
          const existingIds = new Set(prev.map((p) => p.id));
          const newOnes = data.posts.filter((p: any) => !existingIds.has(p.id));
          if (newOnes.length === 0) return prev;
          return [...newOnes, ...prev];
        });
        setHasMore(data.has_more);
      }).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, [tlType]);

  return (
    <>
      <div className="post-form">
        <PostForm onDone={() => setRefreshKey((k) => k + 1)} />
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
          <InfiniteScroll hasMore={hasMore} loadingMore={loadingMore} loadMore={loadMore}>
            {posts.map((p, i) => <div key={p.id} ref={(el) => { cardRefs.current[i] = el; }}><PostCard post={p} onUpdate={load} selected={i === selectedIdx} /></div>)}
          </InfiniteScroll>
        )}
      </div>
      {replyPost && <ReplyModal post={replyPost} onClose={() => setReplyPost(null)} onDone={() => { setReplyPost(null); load(); }} />}
    </>
  );
}
