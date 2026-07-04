"use client";
import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { api, User, PostData, NovelData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import { avatarColor } from "@/lib/avatar";
import Link from "next/link";

export default function ProfilePage() {
  const params = useParams();
  const username = params.username as string;
  const [profile, setProfile] = useState<User | null>(null);
  const [posts, setPosts] = useState<PostData[]>([]);
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [followers, setFollowers] = useState<{ user: User }[]>([]);
  const [following, setFollowing] = useState<{ user: User }[]>([]);
  const [followersCount, setFollowersCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [isFollowing, setIsFollowing] = useState(false);
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("posts");

  const load = async () => {
    setLoading(true);
    try {
      const d = await api.getProfile(username);
      setProfile(d.profile); setPosts(d.posts); setNovels(d.novels);
      setFollowers(d.followers); setFollowing(d.following);
      setFollowersCount(d.followers_count); setFollowingCount(d.following_count);
      setIsFollowing(d.is_following); setIsMine(d.is_mine);
    } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, [username]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (!profile) return <div className="empty-state">사용자를 찾을 수 없습니다.</div>;

  const toggleFollow = async () => {
    try {
      if (isFollowing) { await api.unfollow(username); setIsFollowing(false); setFollowersCount(followersCount - 1); }
      else { await api.follow(username); setIsFollowing(true); setFollowersCount(followersCount + 1); }
    } catch {}
  };

  return (
    <>
      <div className="profile-header">
        <div className="profile-info">
          <div className="profile-avatar" style={{ backgroundColor: avatarColor(profile.username) }}>
            {(profile.display_name || profile.username)[0]}
          </div>
          <div className="profile-info-text">
            <h2>{profile.display_name}</h2>
            <p className="profile-username">@{profile.username}</p>
            {profile.summary && <p className="profile-summary">{profile.summary}</p>}
            <div className="profile-stats">
              <span className={`profile-stat ${tab === "posts" ? "active" : ""}`} onClick={() => setTab("posts")}><strong>{posts.length}</strong> 게시글</span>
              <span className={`profile-stat ${tab === "novels" ? "active" : ""}`} onClick={() => setTab("novels")}><strong>{novels.length}</strong> 소설</span>
              <span className={`profile-stat ${tab === "followers" ? "active" : ""}`} onClick={() => setTab("followers")}><strong>{followersCount}</strong> 팔로워</span>
              <span className={`profile-stat ${tab === "following" ? "active" : ""}`} onClick={() => setTab("following")}><strong>{followingCount}</strong> 팔로잉</span>
            </div>
            {!isMine && (
              <button onClick={toggleFollow} className={`btn ${isFollowing ? "btn-outline" : "btn-primary"}`}>
                <Icon name={isFollowing ? "user" : "user_solid"} /> {isFollowing ? "언팔로우" : "팔로우"}
              </button>
            )}
          </div>
        </div>
      </div>

      <div id="tab-posts" style={{ display: tab === "posts" ? "block" : "none" }}>
        {posts.length === 0 ? <p className="empty-state">게시글이 없습니다.</p> : posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
      </div>

      <div id="tab-novels" className="profile-novel-list" style={{ display: tab === "novels" ? "flex" : "none" }}>
        {novels.length === 0 ? <p className="empty-state">소설이 없습니다.</p> : novels.map((n) => (
          <Link key={n.id} href={`/novels/${n.id}`} className="profile-novel" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <strong className="profile-novel-title">{n.title}</strong>
            <span className="profile-novel-meta">{n.episode_count}화 · {n.is_completed ? "완결" : "연재중"}</span>
            <p className="profile-novel-desc">{n.description || "설명 없음"}</p>
            {n.tags && <p className="novel-tags"><Icon name="tag" />{n.tags}</p>}
          </Link>
        ))}
      </div>

      <div id="tab-followers" className="profile-tab-content" style={{ display: tab === "followers" ? "block" : "none" }}>
        {followers.length === 0 ? <p className="empty-state">팔로워가 없습니다.</p> : followers.map((f) => (
          <Link key={f.user.id} href={`/profile/${f.user.username}`} className="post-card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <div className="profile-user-row">
              <div className="sidebar-avatar" style={{ backgroundColor: avatarColor(f.user.username) }}>
                {(f.user.display_name || f.user.username)[0]}
              </div>
              <div>
                <strong style={{ color: "var(--text-white)" }}>{f.user.display_name}</strong>
                <br /><span className="text-muted">@{f.user.username}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div id="tab-following" className="profile-tab-content" style={{ display: tab === "following" ? "block" : "none" }}>
        {following.length === 0 ? <p className="empty-state">팔로잉이 없습니다.</p> : following.map((f) => (
          <Link key={f.user.id} href={`/profile/${f.user.username}`} className="post-card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <div className="profile-user-row">
              <div className="sidebar-avatar" style={{ backgroundColor: avatarColor(f.user.username) }}>
                {(f.user.display_name || f.user.username)[0]}
              </div>
              <div>
                <strong style={{ color: "var(--text-white)" }}>{f.user.display_name}</strong>
                <br /><span className="text-muted">@{f.user.username}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
