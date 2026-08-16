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

const TAB_KEYS = ["home", "social", "local", "federated"];

const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_STORAGE_KEY = "writ:tl-cache:v3";

interface TimelineCacheEntry {
  posts: PostData[];
  hasMore: boolean;
  cursor: string | null;
  ts: number;
}

function timelineCacheKey(userId: number) {
  return `${CACHE_STORAGE_KEY}:${userId}`;
}

function loadTimelineCache(userId: number): Record<string, TimelineCacheEntry> {
  if (typeof sessionStorage === "undefined") return {};
  try {
    const raw = sessionStorage.getItem(timelineCacheKey(userId));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, TimelineCacheEntry>;
    const now = Date.now();
    const out: Record<string, TimelineCacheEntry> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (v && Array.isArray(v.posts) && now - (v.ts || 0) < CACHE_TTL_MS) out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

function saveTimelineCache(userId: number, cache: Record<string, TimelineCacheEntry>) {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(timelineCacheKey(userId), JSON.stringify(cache));
  } catch {}
}

interface StreamPostData extends PostData {
  type?: "delete" | "update";
}

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

  const timelineCache = useRef<Record<string, TimelineCacheEntry>>({});
  const cacheLoadedRef = useRef<number | null>(null);
  const isReloadRef = useRef<boolean | null>(null);
  const saveTimer = useRef<number | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [replyPost, setReplyPost] = useState<PostData | null>(null);
  const [showComposer, setShowComposer] = useState(false);
  const [rewriteContent, setRewriteContent] = useState<string | null>(null);
  const [rewriteVisibility, setRewriteVisibility] = useState<string | undefined>(undefined);
  const [rewriteSummary, setRewriteSummary] = useState<string | undefined>(undefined);
  const [rewriteInitialContent, setRewriteInitialContent] = useState<string | undefined>(undefined);
  const [rewriteInitialSummary, setRewriteInitialSummary] = useState<string | undefined>(undefined);
  const [rewriteMedia, setRewriteMedia] = useState<{ url: string; type: string; alt?: string }[]>([]);
  const [rewriteInitialMedia, setRewriteInitialMedia] = useState<{ url: string; type: string; alt?: string }[]>([]);
  const [composerCollapsed, setComposerCollapsed] = useState(
    () => typeof localStorage !== "undefined" && localStorage.getItem("writ:timeline-composer-collapsed") === "1"
  );

  const totalLoadedRef = useRef(0);
  const cursorRef = useRef<string | null>(null);
  const loadIdRef = useRef(0);
  const deletedIds = useRef<Set<number>>(new Set());
  const emojiPickerOpenRef = useRef(false);
  const pendingPostsRef = useRef<PostData[]>([]);
  const cardRefs = useRef(new Map<string, HTMLDivElement>());
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

  const selectedIdx = useMemo(() => {
    if (selectedId === null) return -1;
    return filteredPosts.findIndex((p) => p.id === selectedId);
  }, [filteredPosts, selectedId]);
  const selectedIdRef = useRef<number | null>(null);
  useEffect(() => { selectedIdRef.current = selectedId; }, [selectedId]);

  const flushCache = useCallback(() => {
    if (saveTimer.current) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    const uid = accountSnapshot();
    if (uid) saveTimelineCache(uid, timelineCache.current);
  }, []);

  const setCache = useCallback((type: string, entry: TimelineCacheEntry) => {
    timelineCache.current = { ...timelineCache.current, [type]: entry };
    if (saveTimer.current) return;
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      const uid = accountSnapshot();
      if (uid) saveTimelineCache(uid, timelineCache.current);
    }, 2000);
  }, []);

  useEffect(() => {
    const flush = () => flushCache();
    const onVisibility = () => { if (document.visibilityState === "hidden") flushCache(); };
    window.addEventListener("pagehide", flush);
    window.addEventListener("beforeunload", flush);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", flush);
      window.removeEventListener("beforeunload", flush);
      document.removeEventListener("visibilitychange", onVisibility);
      flushCache();
    };
  }, [flushCache]);

  const load = useCallback(async (force = false) => {
    const uid = accountSnapshot();
    if (uid && cacheLoadedRef.current !== uid) {
      if (isReloadRef.current === null) {
        let reload = false;
        try {
          if (typeof window !== "undefined") {
            const nav = performance.getEntriesByType("navigation")[0] as { type?: string } | undefined;
            reload = nav?.type === "reload";
          }
        } catch {}
        isReloadRef.current = reload;
      }
      timelineCache.current = isReloadRef.current ? {} : loadTimelineCache(uid);
      isReloadRef.current = false;
      cacheLoadedRef.current = uid;
    }
    const entry = timelineCache.current[tlType];
    const cached = !force && entry && Date.now() - entry.ts < CACHE_TTL_MS ? entry : null;
    if (cached) {
      setPosts(cached.posts);
      setHasMore(cached.hasMore);
      totalLoadedRef.current = cached.posts.length;
      cursorRef.current = cached.cursor;
      setLoading(false);
      setError("");
      return;
    }
    const loadId = ++loadIdRef.current;
    setLoading(true);
    setError("");
    const snapshot = accountSnapshot();
    try {
      const data = await api.timeline(tlType, LIMIT);
      if (loadId !== loadIdRef.current || accountSnapshot() !== snapshot) return;
      if (data._emojis) injectEmojis(data._emojis);
      setPosts(data.posts);
      setHasMore(data.has_more);
      totalLoadedRef.current = data.posts.length;
      cursorRef.current = data.cursor ?? null;
      setCache(tlType, { posts: data.posts, hasMore: data.has_more, cursor: cursorRef.current, ts: Date.now() });
    } catch (e: unknown) {
      if (loadId !== loadIdRef.current || accountSnapshot() !== snapshot) return;
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
    setLoading(false);
  }, [tlType, setCache]);

  const addOrUpdatePost = useCallback((newPost: PostData) => {
    const c = timelineCache.current[tlType];
    const cachedIdx = c ? c.posts.findIndex((p) => p.id === newPost.id) : -1;
    const inList = cachedIdx >= 0;
    // 로컬/연합 타임라인은 공개 글만 노출한다. 공개가 아닌 새 글(예: 홈)이
    // 작성자 본인의 피드 갱신으로 맨 위에 끼어드는 것을 막는다.
    // (서버 스트림/조회는 이미 필터링되며, 여기는 작성 직후 반환 JSON 경로다.)
    if (!inList && tlType !== "home" && tlType !== "social" && newPost.visibility !== "public") return;
    if (!inList) totalLoadedRef.current += 1;
    setPosts((prev) => {
      const idx = prev.findIndex((p) => p.id === newPost.id);
      let next: PostData[];
      if (idx >= 0) {
        next = [...prev];
        next[idx] = newPost;
      } else {
        next = [newPost, ...prev];
      }
      if (c) setCache(tlType, { ...c, posts: next, cursor: c.cursor, ts: Date.now() });
      return next;
    });
  }, [tlType, setCache]);

  const prependPosts = useCallback((newPosts: PostData[]) => {
    if (newPosts.length === 0) return;
    const c = timelineCache.current[tlType];
    const cachedIds = c ? new Set(c.posts.map((p) => p.id)) : new Set();
    const freshCount = newPosts.filter((p) => !cachedIds.has(p.id)).length;
    totalLoadedRef.current += freshCount;
    setPosts((prev) => {
      const existingIds = new Set(prev.map((p) => p.id));
      const fresh = newPosts.filter((p) => !existingIds.has(p.id));
      if (fresh.length === 0) return prev;
      const next = [...fresh, ...prev];
      if (c) setCache(tlType, { ...c, posts: next, cursor: c.cursor, ts: Date.now() });
      return next;
    });
  }, [tlType, setCache]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const _tl = tlType;
    try {
      const snapshot = accountSnapshot();
      const data = await api.timeline(_tl, LOAD_MORE, cursorRef.current);
      // 요청이 진행되는 동안 탭(tlType)이나 계정이 바뀌었으면 이전 탭의 응답이
      // 현재 탭의 타임라인에 섞여 들어가지 않도록 폐기한다.
      if (accountSnapshot() === snapshot && tlTypeRef.current === _tl) {
        if (data._emojis) injectEmojis(data._emojis);
        const newTotal = totalLoadedRef.current + data.posts.length;
        const newHasMore = data.has_more && newTotal < 500;
        totalLoadedRef.current = newTotal;
        cursorRef.current = data.cursor ?? null;
        setHasMore(newHasMore);
        setPosts((prev) => {
          const next = [...prev, ...data.posts];
          setCache(_tl, { posts: next, hasMore: newHasMore, cursor: cursorRef.current, ts: Date.now() });
          return next;
        });
      }
    } catch (e) {
      console.error("Failed to load more posts:", e);
    }
    setLoadingMore(false);
  }, [tlType, hasMore, loadingMore, setCache]);

  useEffect(() => {
    if (typeof localStorage !== "undefined") localStorage.setItem("writ:timeline-composer-collapsed", composerCollapsed ? "1" : "0");
  }, [composerCollapsed]);

  useEffect(() => { load(); }, [load, user?.id]);

  useEffect(() => {
    if (typeof localStorage !== "undefined") localStorage.setItem("lastTimelineTab", tlType);
  }, [tlType]);

  useEffect(() => {
    const handler = () => load(true);
    window.addEventListener("followchange", handler);
    return () => window.removeEventListener("followchange", handler);
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
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") setSelectedId(null);
    };
    document.addEventListener("focusin", handler);
    return () => document.removeEventListener("focusin", handler);
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { open?: boolean } | undefined;
      if (detail?.open) {
        emojiPickerOpenRef.current = true;
        return;
      }
      emojiPickerOpenRef.current = false;
      const pending = pendingPostsRef.current;
      pendingPostsRef.current = [];
      if (pending.length > 0) prependPosts(pending);
    };
    document.addEventListener("writ:emoji-picker", handler);
    return () => document.removeEventListener("writ:emoji-picker", handler);
  }, [prependPosts]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const currentPosts = filteredPostsRef.current;
      const selIdx = selectedIdRef.current === null
        ? -1
        : currentPosts.findIndex((p) => p.id === selectedIdRef.current);
      if (e.key === "Escape" && selIdx >= 0) {
        e.preventDefault();
        setSelectedId(null);
        return;
      }
      const currentTabIdx = TAB_KEYS.indexOf(tlType);
      if (e.key === "h" && currentTabIdx > 0) {
        e.preventDefault();
        setSelectedId(null);
        router.push(`/timeline/${TAB_KEYS[currentTabIdx - 1]}`);
        return;
      }
      if (e.key === "l" && currentTabIdx < TAB_KEYS.length - 1) {
        e.preventDefault();
        setSelectedId(null);
        router.push(`/timeline/${TAB_KEYS[currentTabIdx + 1]}`);
        return;
      }
      if (e.key === "j") {
        e.preventDefault();
        const next = selIdx < 0 ? 0 : Math.min(selIdx + 1, currentPosts.length - 1);
        const post = currentPosts[next];
        if (post) {
          setSelectedId(post.id);
          selectedIdRef.current = post.id;
          cardRefs.current.get(String(post.id))?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        return;
      }
      if (e.key === ".") {
        e.preventDefault();
        if (selIdx >= 0 && currentPosts[selIdx]) {
          const id = currentPosts[selIdx].id;
          setPosts((prev) => {
            const idx = prev.findIndex((p) => p.id === id);
            if (idx <= 0) return prev;
            const next = [...prev];
            const [post] = next.splice(idx, 1);
            next.unshift(post);
            const c = timelineCache.current[tlType];
            if (c) setCache(tlType, { ...c, posts: next, ts: Date.now() });
            return next;
          });
        }
        const scroller = document.querySelector(".main-content");
        if (scroller) scroller.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      if (e.key === "k") {
        e.preventDefault();
        const next = Math.max(selIdx - 1, 0);
        const post = currentPosts[next];
        if (post) {
          setSelectedId(post.id);
          selectedIdRef.current = post.id;
          cardRefs.current.get(String(post.id))?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        return;
      }
      if (selIdx >= 0 && currentPosts[selIdx]) {
        const sp = currentPosts[selIdx];
        const targetId = sp.boost_of_id || sp.id;
        if (e.key === "f") {
          e.preventDefault();
          const next = !sp.liked;
          setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, liked: next, likes_count: Math.max(0, (p.likes_count || 0) + (next ? 1 : -1)) } : p));
          (next ? api.like(targetId) : api.unlike(targetId)).catch(() => {
            setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, liked: !next, likes_count: Math.max(0, (p.likes_count || 0) + (next ? -1 : 1)) } : p));
          });
          return;
        }
        if (e.key === "d") {
          e.preventDefault();
          const next = !sp.bookmarked;
          setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, bookmarked: next } : p));
          (next ? api.bookmark(targetId) : api.unbookmark(targetId)).catch(() => {
            setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, bookmarked: !next } : p));
          });
          return;
        }
        if (e.key === "b") {
          e.preventDefault();
          if (!sp.boosted && (sp.visibility === "mention" || (!sp.is_mine && sp.visibility === "followers"))) return;
          const next = !sp.boosted;
          setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, boosted: next, boosts_count: Math.max(0, (p.boosts_count || 0) + (next ? 1 : -1)) } : p));
          (next ? api.boost(targetId) : api.unboost(targetId)).catch(() => {
            setPosts((prev) => prev.map((p) => p.id === sp.id ? { ...p, boosted: !next, boosts_count: Math.max(0, (p.boosts_count || 0) + (next ? -1 : 1)) } : p));
          });
          return;
        }
        if (e.key === "r") { e.preventDefault(); api.getPost(targetId).then((d) => setReplyPost(d)).catch(console.error); return; }
        if (e.key === "Enter") { e.preventDefault(); router.push(sp.boost_of_id ? `/post/${sp.boost_of_id}` : sp.number ? `/@${sp.author.username}/${sp.number}` : `/post/${sp.id}`); return; }
        if (e.key === "x") {
          e.preventDefault();
          const el = cardRefs.current.get(String(sp.id));
          if (el) {
            const boxes = el.querySelectorAll("details.cw-box");
            const anyOpen = Array.from(boxes).some((d) => (d as HTMLDetailsElement).open);
            boxes.forEach((d) => { (d as HTMLDetailsElement).open = !anyOpen; });
          }
          window.dispatchEvent(new CustomEvent("writ:reveal-post", { detail: { postId: sp.id } }));
          return;
        }
        if (e.key === "e") {
          e.preventDefault();
          window.dispatchEvent(new CustomEvent("writ:open-media", { detail: { postId: sp.id } }));
          return;
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tlType, router, user?.id]);

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
          if (selectedIdRef.current === newPost.id) {
            const idx = filteredPostsRef.current.findIndex((p) => p.id === newPost.id);
            const remaining = filteredPostsRef.current.filter((p) => p.id !== newPost.id);
            const repl = remaining[Math.min(Math.max(idx, 0), remaining.length - 1)];
            setSelectedId(repl ? repl.id : null);
          }
          setPosts((prev) => {
            const next = prev.filter((p) => p.id !== newPost.id);
            const c = timelineCache.current[tlType];
            if (c) setCache(tlType, { ...c, posts: next, ts: Date.now() });
            return next;
          });
          return;
        }
        if (newPost.type === "update") {
          setPosts((prev) => {
            const next = prev.map((p) => {
              if (p.id === newPost.id) return { ...p, ...newPost };
              if (p.boost_of_id && p.boost_of_id === newPost.id) {
                return { ...p, ...newPost, id: p.id };
              }
              return p;
            });
            const c = timelineCache.current[tlType];
            if (c) setCache(tlType, { ...c, posts: next, ts: Date.now() });
            return next;
          });
          return;
        }
        if (emojiPickerOpenRef.current) {
          pendingPostsRef.current = [...pendingPostsRef.current, newPost];
          return;
        }
        prependPosts([newPost]);
      } catch (e) {
        console.error("Failed to parse SSE message:", e);
      }
    };
    es.onerror = () => {};
    return () => { es?.close(); };
  }, [tlType, user?.id, setCache, prependPosts]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return <div className="empty-state">로그인이 필요합니다</div>;

  return (
    <>
      {!composerCollapsed && (
        <div className="post-form post-form-desktop">
          <PostForm
            key={rewriteContent !== null ? rewriteContent : "main"}
            onDone={(newPost) => {
              if (newPost) addOrUpdatePost(newPost);
              setRewriteContent(null);
              setRewriteVisibility(undefined);
              setRewriteSummary(undefined);
              setRewriteMedia([]);
            }}
            initialContent={rewriteContent ?? undefined}
            initialVisibility={rewriteVisibility}
            initialSummary={rewriteSummary}
            initialMedia={rewriteMedia}
          />
        </div>
      )}
      <button
        type="button"
        className={`composer-collapse-bar post-form-desktop${composerCollapsed ? " collapsed" : ""}`}
        onClick={() => setComposerCollapsed((v) => !v)}
        title={composerCollapsed ? "작성창 펼치기" : "작성창 접기"}
        aria-label={composerCollapsed ? "작성창 펼치기" : "작성창 접기"}
      >
        <Icon name={composerCollapsed ? "chevron_down" : "chevron_up"} size={16} />
      </button>
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
                  key={p.id}
                  ref={(el) => {
                    if (el) cardRefs.current.set(String(p.id), el);
                    else cardRefs.current.delete(String(p.id));
                  }}
                >
                  <PostCard
                    post={p}
                    onDelete={() => {
                      deletedIds.current.add(p.id);
                      if (selectedIdRef.current === p.id) {
                        const idx = filteredPostsRef.current.findIndex((x) => x.id === p.id);
                        const remaining = filteredPostsRef.current.filter((x) => x.id !== p.id);
                        const repl = remaining[Math.min(Math.max(idx, 0), remaining.length - 1)];
                        setSelectedId(repl ? repl.id : null);
                      }
                      setPosts((prev) => {
                        const next = prev.filter((x) => x.id !== p.id);
                        const c = timelineCache.current[tlType];
                        if (c) setCache(tlType, { ...c, posts: next, ts: Date.now() });
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
                    onRewrite={(content, visibility, summary, replyTo, media) => {
                      if (replyTo) {
                        setRewriteInitialContent(content);
                        setRewriteInitialSummary(summary);
                        setRewriteInitialMedia(media || []);
                        setReplyPost({
                          id: replyTo.id,
                          number: replyTo.number,
                          content: replyTo.content,
                          author: replyTo.author,
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
                        setComposerCollapsed(false);
                        setRewriteContent(content);
                        setRewriteVisibility(visibility);
                        setRewriteSummary(summary);
                        setRewriteMedia(media || []);
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
          onClose={() => { setReplyPost(null); setRewriteInitialContent(undefined); setRewriteInitialSummary(undefined); setRewriteInitialMedia([]); }}
          initialContent={rewriteInitialContent}
          initialSummary={rewriteInitialSummary}
          initialMedia={rewriteInitialMedia}
          onDone={(newPost) => {
            setReplyPost(null);
            setRewriteInitialContent(undefined);
            setRewriteInitialSummary(undefined);
            setRewriteInitialMedia([]);
            if (newPost) addOrUpdatePost(newPost);
          }}
        />
      )}
      <button className="mobile-fab" onClick={() => setShowComposer(true)}>
        <Icon name="pen_solid" size={22} />
      </button>
      {showComposer && (
        <div className="mobile-composer-overlay" onClick={() => { setShowComposer(false); setRewriteContent(null); setRewriteVisibility(undefined); setRewriteSummary(undefined); setRewriteMedia([]); }}>
          <div className="mobile-composer-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-composer-header">
              <span>글쓰기</span>
              <button className="mobile-composer-close" onClick={() => { setShowComposer(false); setRewriteContent(null); setRewriteVisibility(undefined); setRewriteSummary(undefined); setRewriteMedia([]); }}>
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
                setRewriteSummary(undefined);
                setRewriteMedia([]);
              }}
              initialContent={rewriteContent ?? undefined}
              initialVisibility={rewriteVisibility}
              initialSummary={rewriteSummary}
              initialMedia={rewriteMedia}
            />
          </div>
        </div>
      )}
    </>
  );
}
