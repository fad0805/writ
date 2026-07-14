"use client";
import { useParams } from "next/navigation";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Head from "next/head";

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

export default function PostByNumberPage() {
  const params = useParams();
  const [post, setPost] = useState<PostData | null>(null);
  const [replies, setReplies] = useState<PostData[]>([]);
  const [totalReplies, setTotalReplies] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const offsetRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const currentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (post) currentRef.current?.scrollIntoView({ behavior: "auto", block: "center" });
  }, [post]);

  const loadPost = async () => {
    setLoading(true);
    offsetRef.current = 0;
    try {
      const username = Array.isArray(params.username) ? params.username[0] : params.username;
      const number = Array.isArray(params.number) ? params.number[0] : params.number;
      if (!username || !number) return;
      const data = await fetch(`/api/by-number/${username}/${number}`, { credentials: "include" });
      const p = await data.json();
      const full = await api.getPost(p.id, 0, 5);
      setPost(full);
      setReplies(full.replies || []);
      setTotalReplies(full.total_replies);
      setHasMore(full.has_more_replies);
    } catch { setPost(null); }
    setLoading(false);
  };

  useEffect(() => { loadPost(); }, [params.username, params.number]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || !post) return;
    setLoadingMore(true);
    offsetRef.current += 5;
    try {
      const data = await api.getPost(post.id, offsetRef.current, 5);
      setReplies((prev) => [...prev, ...(data.replies || [])]);
      setHasMore(data.has_more_replies);
    } catch {}
    setLoadingMore(false);
  }, [post, loadingMore, hasMore]);

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
  if (deleted) return <div className="empty-state">삭제된 게시글입니다.</div>;
  if (!post) return <div className="empty-state">게시글을 찾을 수 없습니다.</div>;

  const username = Array.isArray(params.username) ? params.username[0] : params.username;
  const number = Array.isArray(params.number) ? params.number[0] : params.number;

  return (
    <>
      <Head>
        <link rel="alternate" type="application/activity+json" href={`/@${username}/${number}`} />
        <meta property="og:title" content={`${post.author.display_name || post.author.username} — WRIT`} />
        <meta property="og:description" content={post.content.replace(/<[^>]*>/g, "").slice(0, 200)} />
        <meta property="og:type" content="article" />
        <meta property="og:image" content="/icons/icon-512.png" />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:title" content={`${post.author.display_name || post.author.username} — WRIT`} />
        <meta name="twitter:description" content={post.content.replace(/<[^>]*>/g, "").slice(0, 200)} />
        <meta name="twitter:image" content="/icons/icon-512.png" />
      </Head>
      {ancestors.map((a) => (
        <div key={a.id} className="thread-child"><PostCard post={a} hideContext /></div>
      ))}
      <div ref={currentRef}><PostCard post={post} current hideContext onUpdate={() => loadPost()} onDelete={() => setDeleted(true)} /></div>
      <div className="thread-list">
        <h4>답글 {totalReplies}개</h4>
        <ThreadList posts={replies} parentId={post.id} depth={0} />
        <div ref={sentinelRef} className="sentinel" />
        {loadingMore && <p className="empty-state">불러오는 중...</p>}
      </div>
    </>
  );
}
