"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";

function ThreadNode({ post, depth = 0, onDelete }: { post: PostData; depth?: number; onDelete?: () => void }) {
  return (
    <div style={{ marginLeft: 20 + depth * 16 }}>
      <PostCard post={post} hideContext onDelete={onDelete} />
    </div>
  );
}

function ThreadList({ posts, parentId, depth = 0, onDelete }: { posts: PostData[]; parentId: number; depth?: number; onDelete?: (id: number) => void }) {
  const children = posts
    .filter((p) => p.reply_context?.id === parentId && !p.is_deleted)
    .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  if (children.length === 0) return null;
  return (
    <>
      {children.map((child) => (
        <div key={child.id}>
          <ThreadNode post={child} depth={depth} onDelete={() => onDelete?.(child.id)} />
          <ThreadList posts={posts} parentId={child.id} depth={depth + 1} onDelete={onDelete} />
        </div>
      ))}
    </>
  );
}

export default function PostDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [post, setPost] = useState<PostData | null>(null);
  const [ancestors, setAncestors] = useState<PostData[]>([]);
  const [hasMoreAncestors, setHasMoreAncestors] = useState(false);
  const [loadingAncestors, setLoadingAncestors] = useState(false);
  const [replies, setReplies] = useState<PostData[]>([]);
  const [totalReplies, setTotalReplies] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [showRestrictedWarning, setShowRestrictedWarning] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const offsetRef = useRef(0);
  const ancOffsetRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const currentRef = useRef<HTMLDivElement>(null);

  const initialLoadDone = useRef(false);
  useEffect(() => {
    if (post) {
      if (initialLoadDone.current) {
        currentRef.current?.scrollIntoView({ behavior: "auto", block: "center" });
      }
      initialLoadDone.current = true;
    }
  }, [post]);

  const load = useCallback(async () => {
    setLoading(true);
    offsetRef.current = 0;
    ancOffsetRef.current = 0;
    try {
      const id = Number(params.id);
      if (isNaN(id)) return;
      const data = await api.getPost(id, 0, 50, 0);
      setPost(data);
      setAncestors(data.ancestors || []);
      setHasMoreAncestors(data.has_more_ancestors || false);
      setReplies(data.replies || []);
      setTotalReplies(data.total_replies);
      setHasMore(data.has_more_replies);
      offsetRef.current = 50;
      if (data.author?.is_limited && !data.is_mine && !data.is_following_author) {
        setShowRestrictedWarning(true);
      }
    } catch {}
    setLoading(false);
  }, [params.id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!post?.id) return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/posts/${post.id}/stream`);
    } catch { return; }
    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "update" && msg.id && msg.reactions) {
          setPost((prev) => prev && prev.id === msg.id ? { ...prev, reactions: msg.reactions } : prev);
          setReplies((prev) => prev.map((r) => r.id === msg.id ? { ...r, reactions: msg.reactions } : r));
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es?.close(); };
  }, [post?.id]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    offsetRef.current += 20;
    try {
      const id = Number(params.id);
      if (isNaN(id)) return;
      const data = await api.getPost(id, offsetRef.current, 20, ancOffsetRef.current);
      setReplies((prev) => {
        const seen = new Set(prev.map((r) => r.id));
        const fresh = (data.replies || []).filter((r) => !seen.has(r.id));
        const combined = [...prev, ...fresh];
        return combined.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      });
      setHasMore(data.has_more_replies);
    } catch {}
    setLoadingMore(false);
  }, [params.id, loadingMore, hasMore]);

  const loadMoreAncestors = useCallback(async () => {
    if (loadingAncestors || !hasMoreAncestors || !post) return;
    setLoadingAncestors(true);
    ancOffsetRef.current += 20;
    try {
      const data = await api.getPost(post.id, offsetRef.current, 20, ancOffsetRef.current);
      setAncestors((prev) => [...(data.ancestors || []), ...prev]);
      setHasMoreAncestors(data.has_more_ancestors || false);
    } catch {}
    setLoadingAncestors(false);
  }, [post, loadingAncestors, hasMoreAncestors]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) loadMore(); },
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  useEffect(() => {
    const el = topSentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) loadMoreAncestors(); },
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMoreAncestors]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (deleted) return <div className="empty-state">삭제된 게시글입니다.</div>;
  if (!post) return <div className="empty-state">게시글을 찾을 수 없습니다.</div>;

  if (showRestrictedWarning && post.author?.is_limited) {
    return (
      <div className="card" style={{ padding: 32, maxWidth: 480, margin: "40px auto", textAlign: "center" }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
        <h3 style={{ marginBottom: 8 }}>제한된 사용자의 게시글</h3>
        <p style={{ color: "var(--text-secondary)", marginBottom: 24, fontSize: 14, lineHeight: 1.6 }}>
          이 게시글의 작성자 <strong>{post.author.display_name || post.author.username}</strong> 님은
          관리자에 의해 제한된 계정입니다. 게시글에 부적절한 내용이 포함되어 있을 수 있습니다.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <button className="btn btn-outline" onClick={() => router.back()}>돌아가기</button>
          <button className="btn btn-primary" onClick={() => setShowRestrictedWarning(false)}>계속 보기</button>
        </div>
      </div>
    );
  }

  return (
    <>
      {loadingAncestors && <p className="empty-state">위쪽 불러오는 중...</p>}
      {hasMoreAncestors && <div ref={topSentinelRef} className="sentinel" style={{ height: 1 }} />}
      {ancestors.filter((a) => !a.is_deleted).map((a) => (
        <div key={a.id} className="thread-child"><PostCard post={a} hideContext onDelete={() => setAncestors((prev) => prev.filter((x) => x.id !== a.id))} /></div>
      ))}
      <div ref={currentRef}><PostCard post={post} onUpdate={load} onReply={(newPost) => { if (newPost) { setReplies((prev) => [...prev, newPost]); setTotalReplies((prev) => prev + 1); } }} onDelete={() => setDeleted(true)} current hideContext /></div>
      <div className="thread-list">
        <h4>답글 {totalReplies}개</h4>
        <ThreadList posts={replies} parentId={post.id} depth={0} onDelete={(id) => { setReplies((prev) => prev.filter((r) => r.id !== id)); setTotalReplies((prev) => prev - 1); }} />
        <div ref={sentinelRef} className="sentinel" />
        {loadingMore && <p className="empty-state">불러오는 중...</p>}
      </div>
    </>
  );
}
