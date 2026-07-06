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
import ConfirmModal from "@/components/ConfirmModal";

export default function ProfilePage() {
  const params = useParams();
  const router = useRouter();
  const [showMention, setShowMention] = useState(false);
  const [showRemoveFollower, setShowRemoveFollower] = useState(false);
  const username = params.username as string;
  const [profile, setProfile] = useState<User | null>(null);
  const [posts, setPosts] = useState<PostData[]>([]);
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [followers, setFollowers] = useState<{ user: User }[]>([]);
  const [following, setFollowing] = useState<{ user: User }[]>([]);
  const [followersCount, setFollowersCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [isFollowing, setIsFollowing] = useState(false);
  const [isFollowPending, setIsFollowPending] = useState(false);
  const [hasPendingFollower, setHasPendingFollower] = useState(false);
  const [isFollower, setIsFollower] = useState(false);
  const [approvedFollower, setApprovedFollower] = useState<boolean | null>(null);
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
      setIsFollowing(d.is_following); setIsFollowPending(d.is_follow_pending); setHasPendingFollower(d.has_pending_follower); setIsMine(d.is_mine);
    } catch {}
    setLoading(false);
  }, [username]);

  useEffect(() => {
    api.getProfile(username)
      .then((d) => {
        setProfile(d.profile); setPosts(d.posts); setNovels(d.novels);
        setFollowers(d.followers); setFollowing(d.following);
        setFollowersCount(d.followers_count); setFollowingCount(d.following_count);
      setIsFollowing(d.is_following); setIsFollowPending(d.is_follow_pending); setHasPendingFollower(d.has_pending_follower); setIsFollower(d.is_follower); setApprovedFollower(null); setIsMine(d.is_mine);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [username, router]);

  if (loading) return <div className="empty-state">로딩 중...</div>;
  if (!profile) return <div className="empty-state">사용자를 찾을 수 없습니다.</div>;

  const toggleFollow = async () => {
    try {
      if (isFollowing) { await api.unfollow(username); setIsFollowing(false); setFollowersCount(followersCount - 1); }
      else if (isFollowPending) { await api.unfollow(username); setIsFollowPending(false); }
      else { await api.follow(username); if (profile?.is_locked) setIsFollowPending(true); else { setIsFollowing(true); setFollowersCount(followersCount + 1); } }
      window.dispatchEvent(new Event("followchange"));
    } catch {}
  };

  return (
    <>
      <div className="profile-header">
        <div className="profile-info">
          <div className="profile-avatar-col">
            <Avatar user={profile} className="profile-avatar" />
            {!isMine && (
              <button onClick={toggleFollow} className={`btn btn-small btn-follow ${isFollowing ? "btn-outline" : isFollowPending ? "btn-outline" : "btn-primary"}`} style={{ width: 80, justifyContent: "center", marginBottom: 12 }}>
                {isFollowing ? "언팔로우" : isFollowPending ? "요청됨" : "팔로우"}
              </button>
            )}
          </div>
          <div className="profile-info-relative">
            {(isFollower || hasPendingFollower || approvedFollower === true) && (
              <div className="profile-corner-actions">
                {(isFollower || approvedFollower === true) && (
                  <span
                    onClick={() => setShowRemoveFollower(true)}
                    className="profile-follower-status"
                    title="팔로워 삭제"
                  >
                    <Icon name="user_solid" size={14} /> {isFollowing || approvedFollower === true ? "맞팔로우" : "내 팔로워"}
                  </span>
                )}
                {hasPendingFollower && (
                  <>
                    <button onClick={async () => { await fetch(`/api/users/${profile.username}/approve-follow`, { method: "POST", credentials: "include" }); setHasPendingFollower(false); setApprovedFollower(true); }} className="btn btn-primary btn-small btn-follow">팔로우 수락</button>
                    <button onClick={async () => { await fetch(`/api/users/${profile.username}/reject-follow`, { method: "POST", credentials: "include" }); setHasPendingFollower(false); setApprovedFollower(false); }} className="btn btn-small btn-follow text-muted">거절</button>
                  </>
                )}
              </div>
            )}
            <h2>{profile.display_name} {profile.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.7em", verticalAlign: "middle", color: "var(--text-muted)" }} />} {(profile.role === "admin" || profile.role === "moderator") && (isMine || (profile as any).show_badge) && <Icon name="shield_filled" style={{ color: profile.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.75em", verticalAlign: "middle", marginLeft: 3 }} title={profile.role === "admin" ? "관리자" : "조율자"} />}</h2>
            <p className="profile-username">@{profile.username}</p>
            {profile.summary && (
              <p className="profile-summary" dangerouslySetInnerHTML={{
                __html: profile.summary
                  .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
                  .replace(/<[^>]+\s+on\w+\s*=\s*[^>]*>/gi, '')
                  .replace(/<img[^>]*>/gi, '')
                  .replace(/<iframe[^>]*>[\s\S]*?<\/iframe>/gi, '')
                  .replace(/<object[^>]*>[\s\S]*?<\/object>/gi, '')
                  .replace(/<embed[^>]*>/gi, '')
                  .replace(/\n/g, '<br>')
                  .replace(/<a\s+href="https?:\/\/([^/]+)\/@(\w+)"[^>]*>([^<]*)<\/a>/gi,
                    (_m: string, domain: string, user: string) =>
                      `<a href="/@${user}@${domain}" class="mention-link">@${user}@${domain}</a>`
                  )
              }} />
            )}
            <div className="profile-bottom-actions">
              {isMine ? (
                <button onClick={() => router.push("/users/profile/edit")} className="action-btn btn-action-sm">
                  <Icon name="edit" /> 편집
                </button>
              ) : (
                <>
                  <button className="action-btn btn-action-sm" onClick={() => setShowMention(true)}>
                    <Icon name="mention" /> 멘션
                  </button>
                  <button className="action-btn btn-action-sm" onClick={() => router.push(`/direct/${profile.id}`)}>
                    <Icon name="mail" /> DM
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
      {showMention && <MentionModal username={profile.username} onClose={() => setShowMention(false)} onDone={() => setShowMention(false)} />}
      {showRemoveFollower && (
        <ConfirmModal
          message="팔로워를 삭제하시겠습니까?"
          onConfirm={async () => {
            await fetch(`/api/users/${profile.username}/remove-follower`, { method: "POST", credentials: "include" });
            setIsFollower(false); setApprovedFollower(null); setShowRemoveFollower(false);
          }}
          onCancel={() => setShowRemoveFollower(false)}
        />
      )}
      <div className="profile-stats">
        <span className={`profile-stat ${tab === "posts" ? "active" : ""}`} onClick={() => setTab("posts")}><strong>{posts.length}</strong> 게시글</span>
        <span className={`profile-stat ${tab === "novels" ? "active" : ""}`} onClick={() => setTab("novels")}><strong>{novels.length}</strong> 시리즈</span>
        <span className={`profile-stat ${tab === "following" ? "active" : ""}`} onClick={() => setTab("following")}><strong>{followingCount}</strong> 팔로잉</span>
        <span className={`profile-stat ${tab === "followers" ? "active" : ""}`} onClick={() => setTab("followers")}><strong>{followersCount}</strong> 팔로워</span>
      </div>

      <div id="tab-posts" className="profile-tab-posts" style={{ display: tab === "posts" ? "block" : "none" }}>
        {posts.length === 0 ? <p className="empty-state">게시글이 없습니다.</p> : posts.map((p) => <PostCard key={p.id} post={p} onUpdate={load} />)}
      </div>

      <div id="tab-novels" className="profile-novel-list profile-tab-novels" style={{ display: tab === "novels" ? "flex" : "none" }}>
        {novels.length === 0 ? <p className="empty-state">시리즈가 없습니다.</p> : novels.map((n) => (
          <Link key={n.id} href={n.number ? `/series/@${n.author?.username}/${n.number}` : `/series/${n.id}`} className="profile-novel profile-novel-link">
            <div className="cover-wrap-56">
              {n.cover_image ? (
                <img src={n.cover_image} alt="" className="cover-img" />
              ) : (
                <div className="cover-fallback" style={{ backgroundColor: hashColor(n.title), fontSize: "1em" }}>
                  <Icon name="book" size={16} />
                </div>
              )}
            </div>
            <div className="novel-card-body-content">
              <strong className="profile-novel-title">{n.title}</strong>
              <span className="profile-novel-meta">{n.episode_count}화 · {n.is_completed ? "완결" : "연재중"}</span>
              <p className="profile-novel-desc">{n.description || "설명 없음"}</p>
              {n.tags && <p className="novel-tags"><Icon name="tag" />{n.tags.split(/[ ,]+/).filter(Boolean).map((t, i) => <span key={i} className="tag-spacing">{t}</span>)}</p>}
            </div>
          </Link>
        ))}
      </div>

      <div id="tab-following" className="profile-tab-content" style={{ display: tab === "following" ? "block" : "none" }}>
        {following.length === 0 ? <p className="empty-state">팔로잉이 없습니다.</p> : following.map((f) => (
          <Link key={f.user.id} href={`/@${f.user.username}`} className="post-card tab-content-link">
            <div className="profile-user-row">
              <Avatar user={f.user} className="sidebar-avatar" />
              <div>
                <strong className="follower-name">{f.user.display_name}</strong>
                <br /><span className="text-muted">@{f.user.username}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div id="tab-followers" className="profile-tab-content" style={{ display: tab === "followers" ? "block" : "none" }}>
        {followers.length === 0 ? <p className="empty-state">팔로워가 없습니다.</p> : followers.map((f) => (
          <Link key={f.user.id} href={`/@${f.user.username}`} className="post-card tab-content-link">
            <div className="profile-user-row">
              <Avatar user={f.user} className="sidebar-avatar" />
              <div>
                <strong className="follower-name">{f.user.display_name}</strong>
                <br /><span className="text-muted">@{f.user.username}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
