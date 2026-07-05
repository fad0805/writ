"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { api, User, PostData, NovelData } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import { hashColor } from "@/lib/avatar";
import Link from "next/link";
import Avatar from "@/components/Avatar";
import MentionModal from "@/components/MentionModal";

export default function ProfilePage() {
  const params = useParams();
  const router = useRouter();
  const [showMention, setShowMention] = useState(false);
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.getProfile(username);
      setProfile(d.profile); setPosts(d.posts); setNovels(d.novels);
      setFollowers(d.followers); setFollowing(d.following);
      setFollowersCount(d.followers_count); setFollowingCount(d.following_count);
      setIsFollowing(d.is_following); setIsMine(d.is_mine);
    } catch {}
    setLoading(false);
  }, [username]);

  useEffect(() => {
    api.getProfile(username)
      .then((d) => {
        setProfile(d.profile); setPosts(d.posts); setNovels(d.novels);
        setFollowers(d.followers); setFollowing(d.following);
        setFollowersCount(d.followers_count); setFollowingCount(d.following_count);
        setIsFollowing(d.is_following); setIsMine(d.is_mine);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [username, router]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (!profile) return <div className="empty-state">사용자를 찾을 수 없습니다.</div>;

  const toggleFollow = async () => {
    try {
      if (isFollowing) { await api.unfollow(username); setIsFollowing(false); setFollowersCount(followersCount - 1); }
      else { await api.follow(username); setIsFollowing(true); setFollowersCount(followersCount + 1); }
      window.dispatchEvent(new Event("followchange"));
    } catch {}
  };

  return (
    <>
      <div className="profile-header">
        <div className="profile-info">
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <Avatar user={profile} className="profile-avatar" />
            {!isMine && (
              <button onClick={toggleFollow} className={`btn btn-small ${isFollowing ? "btn-outline" : "btn-primary"}`} style={{ fontSize: "0.82em", width: 80, justifyContent: "center", marginBottom: 12 }}>
                {isFollowing ? "언팔로우" : "팔로우"}
              </button>
            )}
          </div>
          <div className="profile-info-text" style={{ position: "relative" }}>
            <h2>{profile.display_name}</h2>
            <p className="profile-username">@{profile.username}</p>
            {profile.summary && (
              <p className="profile-summary" dangerouslySetInnerHTML={{
                __html: profile.summary
                  .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
                  .replace(/\n/g, '<br>')
                  .replace(/<a\s+href="https?:\/\/([^/]+)\/@(\w+)"[^>]*>([^<]*)<\/a>/gi,
                    (_m: string, domain: string, user: string) =>
                      `<a href="/@${user}@${domain}" class="mention-link">@${user}@${domain}</a>`
                  )
              }} />
            )}
            <div style={{ position: "absolute", bottom: 0, right: 0, display: "flex", gap: 6 }}>
              {isMine ? (
                <button onClick={() => router.push("/users/profile/edit")} className="action-btn" style={{ fontSize: "0.85em" }}>
                  <Icon name="edit" /> 편집
                </button>
              ) : (
                <>
                  <button className="action-btn" style={{ fontSize: "0.85em" }} onClick={() => setShowMention(true)}>
                    <Icon name="mention" /> 멘션
                  </button>
                  <button className="action-btn" style={{ fontSize: "0.85em" }} onClick={() => router.push(`/direct/${profile.id}`)}>
                    <Icon name="mail" /> DM
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
      {showMention && <MentionModal username={profile.username} onClose={() => setShowMention(false)} onDone={() => setShowMention(false)} />}
      <div className="profile-stats">
        <span className={`profile-stat ${tab === "posts" ? "active" : ""}`} onClick={() => setTab("posts")}><strong>{posts.length}</strong> 게시글</span>
        <span className={`profile-stat ${tab === "novels" ? "active" : ""}`} onClick={() => setTab("novels")}><strong>{novels.length}</strong> 시리즈</span>
        <span className={`profile-stat ${tab === "following" ? "active" : ""}`} onClick={() => setTab("following")}><strong>{followingCount}</strong> 팔로잉</span>
        <span className={`profile-stat ${tab === "followers" ? "active" : ""}`} onClick={() => setTab("followers")}><strong>{followersCount}</strong> 팔로워</span>
      </div>

      <div id="tab-posts" style={{ display: tab === "posts" ? "block" : "none" }}>
        {posts.length === 0 ? <p className="empty-state">게시글이 없습니다.</p> : posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
      </div>

      <div id="tab-novels" className="profile-novel-list" style={{ display: tab === "novels" ? "flex" : "none" }}>
        {novels.length === 0 ? <p className="empty-state">시리즈가 없습니다.</p> : novels.map((n) => (
          <Link key={n.id} href={n.number ? `/series/@${n.author?.username}/${n.number}` : `/series/${n.id}`} className="profile-novel" style={{ display: "flex", gap: 14, textDecoration: "none", color: "inherit" }}>
            <div style={{ width: 56, aspectRatio: "3/4", borderRadius: 6, flexShrink: 0, overflow: "hidden" }}>
              {n.cover_image ? (
                <img src={n.cover_image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : (
                <div style={{ width: "100%", height: "100%", backgroundColor: hashColor(n.title), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "1em", fontWeight: "bold" }}>
                  <Icon name="book" size={16} />
                </div>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <strong className="profile-novel-title">{n.title}</strong>
              <span className="profile-novel-meta">{n.episode_count}화 · {n.is_completed ? "완결" : "연재중"}</span>
              <p className="profile-novel-desc">{n.description || "설명 없음"}</p>
              {n.tags && <p className="novel-tags"><Icon name="tag" />{n.tags.split(/[ ,]+/).filter(Boolean).map((t, i) => <span key={i} style={{ marginRight: 6 }}>{t}</span>)}</p>}
            </div>
          </Link>
        ))}
      </div>

      <div id="tab-following" className="profile-tab-content" style={{ display: tab === "following" ? "block" : "none" }}>
        {following.length === 0 ? <p className="empty-state">팔로잉이 없습니다.</p> : following.map((f) => (
          <Link key={f.user.id} href={`/@${f.user.username}`} className="post-card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <div className="profile-user-row">
              <Avatar user={f.user} className="sidebar-avatar" />
              <div>
                <strong style={{ color: "var(--text-white)" }}>{f.user.display_name}</strong>
                <br /><span className="text-muted">@{f.user.username}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div id="tab-followers" className="profile-tab-content" style={{ display: tab === "followers" ? "block" : "none" }}>
        {followers.length === 0 ? <p className="empty-state">팔로워가 없습니다.</p> : followers.map((f) => (
          <Link key={f.user.id} href={`/@${f.user.username}`} className="post-card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <div className="profile-user-row">
              <Avatar user={f.user} className="sidebar-avatar" />
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
