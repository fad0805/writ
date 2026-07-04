"use client";
import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import PostForm from "@/components/PostForm";

export default function PostDetailPage() {
  const params = useParams();
  const [post, setPost] = useState<PostData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { const data = await api.getPost(Number(params.id)); setPost(data); } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, [params.id]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (!post) return <div className="empty-state">게시글을 찾을 수 없습니다.</div>;

  return (
    <>
      {post.ancestors?.map((a) => <PostCard key={a.id} post={a} />)}
      <PostCard post={post} onUpdate={load} current />
      <div className="thread-list">
        <h4>답글 {post.replies?.length || 0}개</h4>
        {post.replies?.map((r) => <PostCard key={r.id} post={r} onUpdate={load} />)}
      </div>
    </>
  );
}
