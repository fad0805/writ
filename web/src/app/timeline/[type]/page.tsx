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
  const [showComposer, setShowComposer] = useState(false);
  const deletedIds = useRef<Set<number>>(new Set());
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

  const touchStartX = useRef(0);

  useEffect(() => {
    const handler = (e: TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
    document.addEventListener("touchstart", handler, { passive: true });
    return () => document.removeEventListener("touchstart", handler);
  }, []);

  useEffect(() => {
    const tabs = ["home", "social", "local", "federated"];
    const currentIdx = tabs.indexOf(tlType);
    const handler = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) < 60) return;
      if (dx > 0 && currentIdx > 0) router.push(`/timeline/${tabs[currentIdx - 1]}`);
      else if (dx < 0 && currentIdx < tabs.length - 1) router.push(`/timeline/${tabs[currentIdx + 1]}`);
    };
    document.addEventListener("touchend", handler, { passive: true });
    return () => document.removeEventListener("touchend", handler);
  }, [tlType, router]);

  useEffect(() => { if (!authLoading && !user) router.replace("/login"); }, [authLoading, user, router]);

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
      const t = ["home", "social", "local", "federated"];
      const currentTabIdx = t.indexOf(tlType);
      if (e.key === "h" && currentTabIdx > 0) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${t[currentTabIdx - 1]}`);
        return;
      }
      if (e.key === "l" && currentTabIdx < t.length - 1) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${t[currentTabIdx + 1]}`);
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
    try {
      es = new EventSource(`/api/timeline/stream?type=${tlType}`);
    } catch { return; }
    es.onmessage = (event) => {
      try {
        const newPost = JSON.parse(event.data);
        if (deletedIds.current.has(newPost.id)) return;
        if (newPost.type === "delete") {
          setPosts((prev) => prev.filter((p) => p.id !== newPost.id));
          const cached = tabCache.current[tlType];
          if (cached) {
            tabCache.current[tlType] = { ...cached, posts: cached.posts.filter((p: any) => p.id !== newPost.id) };
          }
          return;
        }
        if (newPost.type === "update") {
          setPosts((prev) => prev.map((p) => p.id === newPost.id ? { ...p, ...newPost } : p));
          const cached = tabCache.current[tlType];
          if (cached) {
            tabCache.current[tlType] = { ...cached, posts: cached.posts.map((p: any) => p.id === newPost.id ? { ...p, ...newPost } : p) };
          }
          return;
        }
        setPosts((prev) => {
          if (prev.some((p) => p.id === newPost.id)) return prev;
          return [newPost, ...prev];
        });
        const cached = tabCache.current[tlType];
        if (cached && !cached.posts.some((p: any) => p.id === newPost.id)) {
          tabCache.current[tlType] = { ...cached, posts: [newPost, ...cached.posts] };
        }
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
          const newOnes = data.posts.filter((p: any) => !existingIds.has(p.id) && !deletedIds.current.has(p.id));
          if (newOnes.length === 0) return prev;
          return [...newOnes, ...prev];
        });
        setHasMore(data.has_more);
      }).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, [tlType]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return <div className="empty-state">{authLoading ? "로딩 중..." : "로그인이 필요합니다"}</div>;
  return (
    <>
      <div className="post-form post-form-desktop">
        <PostForm onDone={(newPost) => {
          if (newPost) {
            setPosts((prev) => {
              if (prev.some((p) => p.id === newPost.id)) return prev;
              return [newPost, ...prev];
            });
          }
        }} />
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
            {posts.filter((p) => !deletedIds.current.has(p.id)).map((p, i) => <div key={p.id} ref={(el) => { cardRefs.current[i] = el; }}><PostCard post={p} onDelete={() => { deletedIds.current.add(p.id); setPosts((prev) => prev.filter((x) => x.id !== p.id)); }} onUpdate={(updated) => { if (updated) { setPosts((prev) => prev.map((x) => x.id === p.id ? updated : x)); } else { api.getPost(p.id).then((u) => setPosts((prev) => prev.map((x) => x.id === p.id ? u : x))).catch(() => {}); } }} onReply={(newPost) => { if (newPost) { setPosts((prev) => { if (prev.some((x) => x.id === newPost.id)) return prev; return [newPost, ...prev]; }); } }} selected={i === selectedIdx} /></div>)}
          </InfiniteScroll>
        )}
      </div>
      {replyPost && <ReplyModal post={replyPost} onClose={() => setReplyPost(null)} onDone={(newPost) => { setReplyPost(null); if (newPost) { setPosts((prev) => { if (prev.some((p) => p.id === newPost.id)) return prev; return [newPost, ...prev]; }); } }} />}
      <button className="mobile-fab" onClick={() => setShowComposer(true)}>
        <Icon name="pen_solid" size={22} />
      </button>
      {showComposer && (
        <div className="mobile-composer-overlay" onClick={() => setShowComposer(false)}>
          <div className="mobile-composer-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-composer-header">
              <span>글쓰기</span>
              <button className="mobile-composer-close" onClick={() => setShowComposer(false)}>
                <Icon name="x" size={18} />
              </button>
            </div>
            <PostForm onDone={(newPost) => {
              if (newPost) {
                setPosts((prev) => {
                  if (prev.some((p) => p.id === newPost.id)) return prev;
                  return [newPost, ...prev];
                });
              }
              setShowComposer(false);
            }} />
          </div>
        </div>
      )}
    </>
  );
}
