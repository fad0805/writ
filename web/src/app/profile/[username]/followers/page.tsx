"use client";
import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { api, User } from "@/lib/api";
import Link from "next/link";
import Avatar from "@/components/Avatar";
import { getCustomEmojis, renderCustomEmojis, CustomEmoji } from "@/lib/emojis";

export default function FollowersPage() {
  const params = useParams();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);

  useEffect(() => {
    api.getFollowers(params.username as string)
      .then((d) => { setUsers(d.users); setLoading(false); })
      .catch(() => setLoading(false));
  }, [params.username]);

  return (
    <>
      <div className="profile-header">
        <Link href={`/@${params.username}`} className="back-link">← 프로필로</Link>
        <h2 className="section-title">팔로워</h2>
      </div>
      {loading ? <div className="empty-state">로딩 중...</div> : users.length === 0 ? (
        <div className="empty-state">팔로워가 없습니다.</div>
      ) : (
        users.map((u) => (
          <Link key={u.id} href={`/@${u.username}`} className="post-card user-row-card">
            <Avatar user={u} className="post-author-avatar flex items-center justify-center text-white font-bold" />
            <div>
              <div className="post-author" dangerouslySetInnerHTML={{ __html: renderCustomEmojis(u.display_name, emojiMap) }} />
              <div className="post-username">@{u.username}</div>
            </div>
          </Link>
        ))
      )}
    </>
  );
}
