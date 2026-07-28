"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { api, PostData, accountSnapshot } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import PostCard from "@/components/PostCard";
import PostForm from "@/components/PostForm";
import ReplyModal from "@/components/ReplyModal";
import InfiniteScroll from "@/components/InfiniteScroll";
import Icon from "@/components/Icon";
import { injectEmojis } from "@/lib/emojis";
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
  const [error, setError] = useState("");

  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [replyPost, setReplyPost] = useState<PostData | null>(null);
  const [showComposer, setShowComposer] = useState(false);
  const [rewriteContent, setRewriteContent] = useState<string | null>(null);
  const [rewriteVisibility, setRewriteVisibility] = useState<string | undefined>(undefined);
  const [rewriteInitialContent, setRewriteInitialContent] = useState<string | undefined>(undefined);
  
  // 💡 상태 변경 비동기 문제를 해결하기 위해 offset을 최신 ref로 관리합니다.
  const offsetRef = useRef(0);
  const deletedIds = useRef<Set<number>>(new Set());
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const postsRef = useRef(posts);
  postsRef.current = posts;
  const selectedIdxRef = useRef(selectedIdx);
  selectedIdxRef.current = selectedIdx;
  
  const tabCache = useRef<Record<string, { posts: PostData[]; hasMore: boolean; offset: number }>>({});
  const prevTlRef = useRef(tlType);

  useEffect(() => {
    try {
      const accountId = accountSnapshot();
      const raw = localStorage.getItem(`writ:tl-cache:${accountId}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        const ts = parsed._ts || 0;
        if (Date.now() - ts > 5 * 60 * 1000) {
          localStorage.removeItem(`writ:tl-cache:${accountId}`);
        } else {
          delete parsed._ts;
          tabCache.current = parsed;
        }
      }
    } catch {}
  }, []);

  const saveTabCache = () => {
    try { localStorage.setItem(`writ:tl-cache:${accountSnapshot()}`, JSON.stringify({ ...tabCache.current, _ts: Date.now() })); } catch {}
  };

  useEffect(() => {
    if (typeof localStorage !== "undefined") localStorage.setItem("lastTimelineTab", tlType);
    const cacheKey = `${accountSnapshot()}:${tlType}`;
    if (prevTlRef.current !== tlType) {
      const prevKey = `${accountSnapshot()}:${prevTlRef.current}`;
      tabCache.current[prevKey] = { posts, hasMore, offset: offsetRef.current };
      saveTabCache();
      prevTlRef.current = tlType;
    }
    const saved = tabCache.current[cacheKey];
    if (saved) {
      setPosts(saved.posts);
      setHasMore(saved.hasMore);
      offsetRef.current = saved.offset;
      setLoading(false);
      load(true);
      return;
    }
    load();
  }, [tlType, user?.id]);

  const load = async (silent = false) => {
    const snapshot = accountSnapshot();
    if (!silent) setLoading(true);
    setError("");
    try {
      const data = await api.timeline(tlType, LIMIT, 0);
      if (accountSnapshot() !== snapshot) return;
      if (data._emojis) injectEmojis(data._emojis);
      setPosts(data.posts);
      setHasMore(data.has_more);
      offsetRef.current = LIMIT;
      const cacheKey = `${snapshot}:${tlType}`;
      tabCache.current[cacheKey] = { posts: data.posts, hasMore: data.has_more, offset: LIMIT };
      saveTabCache();
    } catch (e: any) {
      if (accountSnapshot() !== snapshot) return;
      setError(e.message || "불러오기 실패");
    }
    setLoading(false);
  };

  useEffect(() => {
    const handler = () => load();
    window.addEventListener("followchange", handler);
    return () => window.removeEventListener("followchange", handler);
  }, [tlType, user?.id]);

  // 💡 의존성 배열을 단순화하여 렉이 걸려도 항상 최신 정보로 백엔드에 페이징을 요청하도록 보장합니다.
  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const snapshot = accountSnapshot();
      const currentOffset = offsetRef.current;
      const data = await api.timeline(tlType, LOAD_MORE, currentOffset);
      if (accountSnapshot() !== snapshot) return;
      if (data._emojis) injectEmojis(data._emojis);
      
      setPosts((prev) => {
        const ids = new Set(prev.map((p) => p.id));
        const newPosts = data.posts.filter((p: any) => !ids.has(p.id));
        const total = prev.length + newPosts.length;
        if (total >= 500) setHasMore(false);
        return [...prev, ...newPosts];
      });
      
      setHasMore(data.has_more);
      offsetRef.current = currentOffset + LOAD_MORE;
      
      const cacheKey = `${snapshot}:${tlType}`;
      const cached = tabCache.current[cacheKey];
      if (cached) {
        tabCache.current[cacheKey].offset = currentOffset + LOAD_MORE;
        tabCache.current[cacheKey].hasMore = data.has_more;
        saveTabCache();
      }
    } catch {}
    setLoadingMore(false);
  }, [tlType, hasMore, loadingMore]);

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
      if ((e.target as HTMLElement).closest(".reply-modal-backdrop")) return;
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) < 120) return;
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
  }, [tlType, user?.id]);

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/timeline/stream?type=${tlType}`);
    } catch { return; }
    es.onmessage = (event) => {
      try {
        const newPost = JSON.parse(event.data);
        if (newPost._emojis) {
          injectEmojis(newPost._emojis);
        }
        if (deletedIds.current.has(newPost.id)) return;
        if (newPost.type === "delete") {
          setPosts((prev) => prev.filter((p) => p.id !== newPost.id));
          const cacheKey = `${accountSnapshot()}:${tlType}`;
          const cached = tabCache.current[cacheKey];
          if (cached) {
            tabCache.current[cacheKey] = { ...cached, posts: cached.posts.filter((p: any) => p.id !== newPost.id) };
            saveTabCache();
          }
          return;
        }
        if (newPost.type === "update") {
          setPosts((prev) => prev.map((p) => p.id === newPost.id ? { ...p, ...newPost } : p));
          const cacheKey = `${accountSnapshot()}:${tlType}`;
          const cached = tabCache.current[cacheKey];
          if (cached) {
            tabCache.current[cacheKey] = { ...cached, posts: cached.posts.map((p: any) => p.id === newPost.id ? { ...p, ...newPost } : p) };
            saveTabCache();
          }
          return;
        }
        setPosts((prev) => {
          if (prev.some((p) => p.id === newPost.id)) return prev;
          return [newPost, ...prev];
        });
        const cacheKey = `${accountSnapshot()}:${tlType}`;
        const cached = tabCache.current[cacheKey];
        if (cached && !cached.posts.some((p: any) => p.id === newPost.id)) {
          tabCache.current[cacheKey] = { ...cached, posts: [newPost, ...cached.posts] };
          saveTabCache();
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es?.close(); };
  }, [tlType, user?.id]);

  // 성능 최적화용 필터링 분리
  const filteredPosts = useMemo(() => {
    return posts.filter((p) => !deletedIds.current.has(p.id));
  }, [posts]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return <div className="empty-state">로그인이 필요합니다</div>;

  return (
    <>
        <div className="post-form post-form-desktop">
          <PostForm key={rewriteContent ? `rewrite-${Date.now()}` : "main"} onDone={(newPost) => {
            if (newPost) {
              setPosts((prev) => {
                if (prev.some((p) => p.id === newPost.id)) return prev;
                return [newPost, ...prev];
              });
            }
            setRewriteContent(null);
            setRewriteVisibility(undefined);
          }} initialContent={rewriteContent ?? undefined} initialVisibility={rewriteVisibility} />
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
        {error ? (
          <p className="empty-state">오류: {error}</p>
        ) : (
          /* 💡 loading 상태와 관계없이 InfiniteScroll은 항상 렌더링 상태를 유지합니다. */
          <InfiniteScroll 
            hasMore={hasMore} 
            loadingMore={loadingMore || loading} 
            loadMore={loadMore}
          >
            {/* 실제 데이터가 로드되었고 포스트가 있을 때만 카드들을 그립니다. */}
            {!loading && filteredPosts.length === 0 ? (
              <p className="empty-state">표시할 글이 없습니다.</p>
            ) : (
              filteredPosts.map((p, i) => (
                <div key={p.id} ref={(el) => { if (el) cardRefs.current[i] = el; }}>
                  <PostCard 
                    post={p} 
                    onDelete={() => { 
                      deletedIds.current.add(p.id); 
                      setPosts((prev) => prev.filter((x) => x.id !== p.id)); 
                    }} 
                    onUpdate={(updated) => { 
                      if (updated) { 
                        setPosts((prev) => prev.map((x) => x.id === p.id ? updated : x)); 
                      } else { 
                        api.getPost(p.id).then((u) => setPosts((prev) => prev.map((x) => x.id === p.id ? u : x))).catch(() => {}); 
                      } 
                    }} 
                    onReply={(newPost) => { 
                      if (newPost) { 
                        setPosts((prev) => { 
                          if (prev.some((x) => x.id === newPost.id)) return prev; 
                          return [newPost, ...prev]; 
                        }); 
                      } 
                    }} 
                    onRewrite={(content, visibility, replyTo) => {
                      if (replyTo) {
                        setRewriteInitialContent(content);
                        setReplyPost({
                          id: replyTo.id,
                          number: replyTo.number,
                          content: replyTo.content,
                          author: replyTo.author,
                          visibility: replyTo.visibility,
                          summary: null,
                          created_at: null,
                          ap_id: "",
                          likes_count: 0, boosts_count: 0, replies_count: 0,
                          liked: false, boosted: false, bookmarked: false, is_mine: false,
                          reply_context: null, media_attachments: [],
                          is_deleted: false,
                        } as any);
                      } else {
                        setRewriteContent(content);
                        setRewriteVisibility(visibility);
                        setShowComposer(true);
                      }
                    }}
                    selected={i === selectedIdx} 
                  />
                </div>
              ))
            )}
          </InfiniteScroll>
        )}
      </div>
      {replyPost && <ReplyModal post={replyPost} onClose={() => { setReplyPost(null); setRewriteInitialContent(undefined); }} initialContent={rewriteInitialContent} onDone={(newPost) => { setReplyPost(null); setRewriteInitialContent(undefined); if (newPost) { setPosts((prev) => { if (prev.some((p) => p.id === newPost.id)) return prev; return [newPost, ...prev]; }); } }} />}
      <button className="mobile-fab" onClick={() => setShowComposer(true)}>
        <Icon name="pen_solid" size={22} />
      </button>
      {showComposer && (
        <div className="mobile-composer-overlay" onClick={() => { setShowComposer(false); setRewriteContent(null); setRewriteVisibility(undefined); }}>
          <div className="mobile-composer-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-composer-header">
              <span>글쓰기</span>
              <button className="mobile-composer-close" onClick={() => { setShowComposer(false); setRewriteContent(null); setRewriteVisibility(undefined); }}>
                <Icon name="x" size={18} />
              </button>
            </div>
            <PostForm key={rewriteContent ? `rewrite-${Date.now()}` : "mobile"} onDone={(newPost) => {
              if (newPost) {
                setPosts((prev) => {
                  if (prev.some((p) => p.id === newPost.id)) return prev;
                  return [newPost, ...prev];
                });
              }
              setShowComposer(false);
              setRewriteContent(null);
              setRewriteVisibility(undefined);
            }} initialContent={rewriteContent ?? undefined} initialVisibility={rewriteVisibility} />
          </div>
        </div>
      )}
    </>
  );
}
