"use client";
import { useEffect, useState } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";

export default function ExplorePage() {
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.explore().then((d) => { setPosts(d.posts); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  return (
    <>
      <h3 className="section-header"><Icon name="star_filled" /> 인기 게시글</h3>
      {loading ? (
        <div className="empty-state">로딩 중...</div>
      ) : posts.length === 0 ? (
        <div className="empty-state">게시글이 없습니다.</div>
      ) : (
        posts.map((p) => <PostCard key={p.id} post={p} />)
      )}
    </>
  );
}
