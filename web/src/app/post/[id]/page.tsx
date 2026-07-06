"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";

function ThreadNode({ post, depth = 0 }: { post: PostData; depth?: number }) {
  return (
    <div style={{ marginLeft: 20 + depth * 16 }}>
      <PostCard post={post} hideContext />
    </div>
  );
}

function ThreadList({ posts, parentId, depth = 0 }: { posts: PostData[]; parentId: number; depth?: number }) {
  const children = posts.filter((p) => p.reply_context?.id === parentId);
  if (children.length === 0) return null;
  return (
    <>
      {children.map((child) => (
        <div key={child.id}>
          <ThreadNode post={child} depth={depth} />
          <ThreadList posts={posts} parentId={child.id} depth={depth + 1} />
        </div>
      ))}
    </>
  );
}

export default function PostDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [post, setPost] = useState<PostData | null>(null);
  const [replies, setReplies] = useState<PostData[]>([]);
  const [totalReplies, setTotalReplies] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const offsetRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    offsetRef.current = 0;
    try {
      const id = Number(params.id);
      if (isNaN(id)) return;
      const data = await api.getPost(id, 0, 5);
      setPost(data);
      setReplies(data.replies || []);
      setTotalReplies(data.total_replies);
      setHasMore(data.has_more_replies);
    } catch {}
    setLoading(false);
  }, [params.id]);

  useEffect(() => { load(); }, [load]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    offsetRef.current += 5;
    try {
      const id = Number(params.id);
      if (isNaN(id)) return;
      const data = await api.getPost(id, offsetRef.current, 5);
      setReplies((prev) => [...prev, ...(data.replies || [])]);
      setHasMore(data.has_more_replies);
    } catch {}
    setLoadingMore(false);
  }, [params.id, loadingMore, hasMore]);

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

  const ancestors = useMemo(() => post?.ancestors || [], [post]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (!post) return <div className="empty-state">게시글을 찾을 수 없습니다.</div>;

  return (
    <>
      {ancestors.map((a) => (
        <div key={a.id} style={{ marginLeft: 20 }}><PostCard post={a} hideContext /></div>
      ))}
      <PostCard post={post} onUpdate={load} onDelete={() => router.push("/timeline/home")} current hideContext />
      <div className="thread-list">
        <h4>답글 {totalReplies}개</h4>
        <ThreadList posts={replies} parentId={post.id} depth={0} />
        <div ref={sentinelRef} style={{ height: 1 }} />
        {loadingMore && <p className="empty-state">불러오는 중...</p>}
      </div>
    </>
  );
}
