"use client";
import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { api, User } from "@/lib/api";
import Link from "next/link";
import { avatarColor } from "@/lib/avatar";

export default function FollowingPage() {
  const params = useParams();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getFollowing(params.username as string)
      .then((d) => { setUsers(d.users); setLoading(false); })
      .catch(() => setLoading(false));
  }, [params.username]);

  return (
    <>
      <div className="profile-header">
        <Link href={`/profile/${params.username}`} className="back-link">← 프로필로</Link>
        <h2 className="section-title">팔로잉</h2>
      </div>
      {loading ? <div className="empty-state">로딩 중...</div> : users.length === 0 ? (
        <div className="empty-state">팔로잉이 없습니다.</div>
      ) : (
        users.map((u) => (
          <Link key={u.id} href={`/profile/${u.username}`} className="post-card user-row-card">
            <div className="post-author-avatar bg-[var(--accent)] flex items-center justify-center text-white font-bold">
              {(u.display_name || u.username)[0]}
            </div>
            <div>
              <div className="post-author">{u.display_name}</div>
              <div className="post-username">@{u.username}</div>
            </div>
          </Link>
        ))
      )}
    </>
  );
}
