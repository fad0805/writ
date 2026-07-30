"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { api, PostData, accountSnapshot, User } from "@/lib/api";
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

const TAB_KEYS = ["home", "social", "local", "federated"];

interface StreamPostData extends PostData {
  type?: "delete" | "update";
  boost_of_id?: number;
  _boost_pointer_id?: number;
}

const postKey = (p: { id: number; boosted_by?: { id: number } | null }) =>
  `${p.id}-${p.boosted_by?.id ?? ""}`;

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

  const timelineCache = useRef<Record<string, { posts: PostData[]; hasMore: boolean; offset: number; totalLoaded: number }>>({});

  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [replyPost, setReplyPost] = useState<PostData | null>(null);
  const [showComposer, setShowComposer] = useState(false);
  const [rewriteContent, setRewriteContent] = useState<string | null>(null);
  const [rewriteVisibility, setRewriteVisibility] = useState<string | undefined>(undefined);
  const [rewriteInitialContent, setRewriteInitialContent] = useState<string | undefined>(undefined);

  const offsetRef = useRef(0);
  const totalLoadedRef = useRef(0);
  const loadIdRef = useRef(0);
  const deletedIds = useRef<Set<number>>(new Set());
  const cardRefs = useRef(new Map<string, HTMLDivElement>());
  const selectedIdxRef = useRef(selectedIdx);
  useEffect(() => { selectedIdxRef.current = selectedIdx; }, [selectedIdx]);
  const touchStartX = useRef(0);
  const tlTypeRef = useRef(tlType);
  useEffect(() => { tlTypeRef.current = tlType; }, [tlType]);

  const filteredPosts = useMemo(
    // eslint-disable-next-line react-hooks/refs -- deletedIds is mutation-only, safe during render
    () => posts.filter((p) => !deletedIds.current.has(p.id)),
    [posts]
  );
  const filteredPostsRef = useRef(filteredPosts);
  // eslint-disable-next-line react-hooks/refs -- sync ref with render output for keyboard handler
  filteredPostsRef.current = filteredPosts;

  const load = useCallback(async () => {
    const cached = timelineCache.current[tlType];
    if (cached) {
      setPosts(cached.posts);
      setHasMore(cached.hasMore);
      offsetRef.current = cached.offset;
      totalLoadedRef.current = cached.totalLoaded;
      setLoading(false);
      setError("");
      return;
    }
    const loadId = ++loadIdRef.current;
    setLoading(true);
    setError("");
    const snapshot = accountSnapshot();
    try {
      const data = await api.timeline(tlType, LIMIT, 0);
      if (loadId !== loadIdRef.current || accountSnapshot() !== snapshot) return;
      if (data._emojis) injectEmojis(data._emojis);
      setPosts(data.posts);
      setHasMore(data.has_more);
      offsetRef.current = LIMIT;
      totalLoadedRef.current = data.posts.length;
      timelineCache.current[tlType] = { posts: data.posts, hasMore: data.has_more, offset: LIMIT, totalLoaded: data.posts.length };
    } catch (e: unknown) {
      if (loadId !== loadIdRef.current || accountSnapshot() !== snapshot) return;
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
    setLoading(false);
  }, [tlType]);

  const addOrUpdatePost = useCallback((newPost: PostData) => {
    setPosts((prev) => {
      const idx = prev.findIndex((p) => p.id === newPost.id);
      let next: PostData[];
      if (idx >= 0) {
        next = [...prev];
        next.splice(idx, 1);
        next = [newPost, ...next];
      } else {
        next = [newPost, ...prev];
      }
      const c = timelineCache.current[tlType];
      if (c) timelineCache.current[tlType] = { ...c, posts: next };
      return next;
    });
  }, [tlType]);

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
        const next = [...prev, ...data.posts];
        timelineCache.current[tlType] = { posts: next, hasMore: data.has_more && totalLoadedRef.current + data.posts.length < 500, offset: currentOffset + LOAD_MORE, totalLoaded: totalLoadedRef.current + data.posts.length };
        return next;
      });
      totalLoadedRef.current += data.posts.length;
      setHasMore(data.has_more && totalLoadedRef.current < 500);
      offsetRef.current = currentOffset + LOAD_MORE;
    } catch (e) {
      console.error("Failed to load more posts:", e);
    }
    setLoadingMore(false);
  }, [tlType, hasMore, loadingMore]);

  useEffect(() => { load(); }, [load, user?.id]);

  useEffect(() => {
    window.addEventListener("followchange", load);
    return () => window.removeEventListener("followchange", load);
  }, [load, user?.id]);

  useEffect(() => {
    const handler = (e: TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
    document.addEventListener("touchstart", handler, { passive: true });
    return () => document.removeEventListener("touchstart", handler);
  }, []);

  useEffect(() => {
    const handler = (e: TouchEvent) => {
      if ((e.target as HTMLElement).closest(".reply-modal-backdrop")) return;
      const currentIdx = TAB_KEYS.indexOf(tlTypeRef.current);
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) < 120) return;
      if (dx > 0 && currentIdx > 0) router.push(`/timeline/${TAB_KEYS[currentIdx - 1]}`);
      else if (dx < 0 && currentIdx < TAB_KEYS.length - 1) router.push(`/timeline/${TAB_KEYS[currentIdx + 1]}`);
    };
    document.addEventListener("touchend", handler, { passive: true });
    return () => document.removeEventListener("touchend", handler);
  }, [router]);

  useEffect(() => { if (!authLoading && !user) router.replace("/login"); }, [authLoading, user, router]);

  useEffect(() => {
    const handler = (e: FocusEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") setSelectedIdx(-1);
    };
    document.addEventListener("focusin", handler);
    return () => document.removeEventListener("focusin", handler);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const selIdx = selectedIdxRef.current;
      const currentPosts = filteredPostsRef.current;
      if (e.key === "Escape" && selIdx >= 0) {
        e.preventDefault();
        setSelectedIdx(-1);
        return;
      }
      const currentTabIdx = TAB_KEYS.indexOf(tlType);
      if (e.key === "h" && currentTabIdx > 0) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${TAB_KEYS[currentTabIdx - 1]}`);
        return;
      }
      if (e.key === "l" && currentTabIdx < TAB_KEYS.length - 1) {
        e.preventDefault();
        setSelectedIdx(-1);
        router.push(`/timeline/${TAB_KEYS[currentTabIdx + 1]}`);
        return;
      }
      if (e.key === "j") {
        e.preventDefault();
        setSelectedIdx((prev) => {
          const next = prev < 0 ? 0 : Math.min(prev + 1, currentPosts.length - 1);
          const post = currentPosts[next];
          if (post) cardRefs.current.get(postKey(post))?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          return next;
        });
        return;
      }
      if (e.key === "k") {
        e.preventDefault();
        setSelectedIdx((prev) => {
          const next = Math.max(prev - 1, 0);
          const post = currentPosts[next];
          if (post) cardRefs.current.get(postKey(post))?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          return next;
        });
        return;
      }
      if (selIdx >= 0 && currentPosts[selIdx]) {
        const sp = currentPosts[selIdx];
        const targetId = sp.boost_of_id || sp.id;
        if (e.key === "f") { e.preventDefault(); (sp.liked ? api.unlike(targetId) : api.like(targetId)).then(() => load()).catch(console.error); return; }
        if (e.key === "d") { e.preventDefault(); (sp.bookmarked ? api.unbookmark(targetId) : api.bookmark(targetId)).then(() => load()).catch(console.error); return; }
        if (e.key === "b") { e.preventDefault(); (sp.boosted ? api.unboost(targetId) : api.boost(targetId)).then(() => load()).catch(console.error); return; }
        if (e.key === "r") { e.preventDefault(); api.getPost(targetId).then((d) => setReplyPost(d)).catch(console.error); return; }
        if (e.key === "Enter") { e.preventDefault(); router.push(sp.boost_of_id ? `/post/${sp.boost_of_id}` : sp.number ? `/@${sp.author.username}/${sp.number}` : `/post/${sp.id}`); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tlType, load, router, user?.id]);

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/timeline/stream?type=${tlType}`);
    } catch { return; }
    es.onmessage = (event) => {
      try {
        const newPost: StreamPostData = JSON.parse(event.data);
        if (newPost._emojis) injectEmojis(newPost._emojis);
        if (deletedIds.current.has(newPost.id)) return;
        if (newPost.type === "delete") {
          setPosts((prev) => {
            const next = prev.filter(
              (p) => p.id !== newPost.id && (p as StreamPostData)._boost_pointer_id !== newPost.id
            );
            const c = timelineCache.current[tlType];
            if (c) timelineCache.current[tlType] = { ...c, posts: next };
            return next;
          });
          return;
        }
        if (newPost.type === "update") {
          setPosts((prev) => {
            const next = prev.map((p) => p.id === newPost.id ? { ...p, ...newPost } : p);
            const c = timelineCache.current[tlType];
            if (c) timelineCache.current[tlType] = { ...c, posts: next };
            return next;
          });
          return;
        }
        setPosts((prev) => {
          let next: PostData[];
          if (newPost.boost_of_id) {
            const idx = prev.findIndex(
              (p) => p.id === newPost.id && p.boosted_by?.id === newPost.boosted_by?.id
            );
            if (idx >= 0) {
              next = [...prev];
              next.splice(idx, 1);
              next = [newPost, ...next];
            } else {
              next = [newPost, ...prev];
            }
          } else {
            const idx = prev.findIndex((p) => p.id === newPost.id);
            if (idx >= 0) {
              next = [...prev];
              next.splice(idx, 1);
              next = [newPost, ...next];
            } else {
              next = [newPost, ...prev];
            }
          }
          const c = timelineCache.current[tlType];
          if (c) timelineCache.current[tlType] = { ...c, posts: next };
          return next;
        });
      } catch (e) {
        console.error("Failed to parse SSE message:", e);
      }
    };
    es.onerror = () => {};
    return () => { es?.close(); };
  }, [tlType, user?.id]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return <div className="empty-state">로그인이 필요합니다</div>;

  return (
    <>
      <div className="post-form post-form-desktop">
        <PostForm
          key={rewriteContent !== null ? rewriteContent : "main"}
          onDone={(newPost) => {
            if (newPost) addOrUpdatePost(newPost);
            setRewriteContent(null);
            setRewriteVisibility(undefined);
          }}
          initialContent={rewriteContent ?? undefined}
          initialVisibility={rewriteVisibility}
        />
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
          <InfiniteScroll
            hasMore={hasMore}
            loadingMore={loadingMore || loading}
            loadMore={loadMore}
          >
            {!loading && !hasMore && filteredPosts.length === 0 ? (
              <p className="empty-state">표시할 글이 없습니다.</p>
            ) : (
              filteredPosts.map((p, i) => (
                <div
                  key={postKey(p)}
                  ref={(el) => {
                    if (el) cardRefs.current.set(postKey(p), el);
                    else cardRefs.current.delete(postKey(p));
                  }}
                >
                  <PostCard
                    post={p}
                    onDelete={() => {
                      deletedIds.current.add(p.id);
                      setPosts((prev) => {
                        const next = prev.filter((x) => x.id !== p.id);
                        const c = timelineCache.current[tlType];
                        if (c) timelineCache.current[tlType] = { ...c, posts: next };
                        return next;
                      });
                    }}
                    onUpdate={(updated) => {
                      if (updated) {
                        addOrUpdatePost(updated);
                      } else {
                        api.getPost(p.id).then(addOrUpdatePost).catch(console.error);
                      }
                    }}
                    onReply={(newPost) => {
                      if (newPost) addOrUpdatePost(newPost);
                    }}
                    onRewrite={(content, visibility, replyTo) => {
                      if (replyTo) {
                        setRewriteInitialContent(content);
                        setReplyPost({
                          id: replyTo.id,
                          number: replyTo.number,
                          content: replyTo.content,
                          author: replyTo.author as User,
                          visibility: replyTo.visibility,
                          summary: "",
                          created_at: null,
                          ap_id: "",
                          likes_count: 0, boosts_count: 0, replies_count: 0,
                          liked: false, boosted: false, bookmarked: false, is_mine: false,
                          reply_context: null,
                          is_deleted: false,
                        });
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
      {replyPost && (
        <ReplyModal
          post={replyPost}
          onClose={() => { setReplyPost(null); setRewriteInitialContent(undefined); }}
          initialContent={rewriteInitialContent}
          onDone={(newPost) => {
            setReplyPost(null);
            setRewriteInitialContent(undefined);
            if (newPost) addOrUpdatePost(newPost);
          }}
        />
      )}
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
            <PostForm
              key={rewriteContent !== null ? rewriteContent : "mobile"}
              onDone={(newPost) => {
                if (newPost) addOrUpdatePost(newPost);
                setShowComposer(false);
                setRewriteContent(null);
                setRewriteVisibility(undefined);
              }}
              initialContent={rewriteContent ?? undefined}
              initialVisibility={rewriteVisibility}
            />
          </div>
        </div>
      )}
    </>
  );
}
