"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import PostCard from "@/components/PostCard";
import PostForm from "@/components/PostForm";
import ReplyModal from "@/components/ReplyModal";
import Icon from "@/components/Icon";
import Link from "next/link";
import { useStream } from "@/lib/useStream";

const LIMIT = 10;
const LOAD_MORE = 5;

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
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [replyPost, setReplyPost] = useState<PostData | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const postsRef = useRef(posts);
  postsRef.current = posts;
  const selectedIdxRef = useRef(selectedIdx);
  selectedIdxRef.current = selectedIdx;

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

  const loadingRef = useRef(false);
  const loadMoreRef = useRef<() => void>(() => {});
  loadMoreRef.current = () => {
    if (loadingRef.current || !hasMore) return;
    loadingRef.current = true;
    setLoadingMore(true);
    const currentLen = posts.length;
    const currentType = tlType;
    api.timeline(currentType, LOAD_MORE, currentLen).then((data) => {
      setPosts((prev) => [...prev, ...data.posts]);
      setHasMore(data.has_more);
    }).catch(() => {}).finally(() => { loadingRef.current = false; setLoadingMore(false); });
  };

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

  useEffect(() => { load(); }, [tlType, refreshKey]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener("followchange", handler);
    return () => window.removeEventListener("followchange", handler);
  }, [tlType]);

  useStream({
    new_post: () => { load(); },
  });

  useEffect(() => {
    const interval = setInterval(() => {
      api.timeline(tlType, LIMIT, 0).then((data) => {
        setPosts(data.posts);
        setHasMore(data.has_more);
      }).catch(() => {});
    }, 15000);
    return () => clearInterval(interval);
  }, [tlType]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMoreRef.current();
      },
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasMore, posts.length]);

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
          <>
            {posts.map((p, i) => <div key={p.id} ref={(el) => { cardRefs.current[i] = el; }}><PostCard post={p} onUpdate={load} selected={i === selectedIdx} /></div>)}
            <div ref={sentinelRef} className="sentinel" />
            {loadingMore && <p className="empty-state">불러오는 중...</p>}
          </>
        )}
      </div>
      {replyPost && <ReplyModal post={replyPost} onClose={() => setReplyPost(null)} onDone={() => { setReplyPost(null); load(); }} />}
    </>
  );
}
