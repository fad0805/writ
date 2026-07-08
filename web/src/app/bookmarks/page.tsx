"use client";
import { useEffect, useState } from "react";
import { api, PostData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";

export default function BookmarksPage() {
  const [posts, setPosts] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.getBookmarks()
      .then((d) => { setPosts(d.posts); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <>
      <h2><Icon name="bookmark" /> 북마크</h2>
      {loading ? <p className="empty-state">로딩 중...</p> : (
        posts.length === 0 ? <p className="empty-state">북마크한 게시글이 없습니다.</p> : (
          posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)
        )
      )}
    </>
  );
}
