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
  const [showNote, setShowNote] = useState(false);
  const [showMuteModal, setShowMuteModal] = useState(false);
  const [showBlockConfirm, setShowBlockConfirm] = useState(false);
  const [muteDuration, setMuteDuration] = useState(0);
  const [muteHideNotif, setMuteHideNotif] = useState(false);
  const [profileNote, setProfileNote] = useState("");
  const [noteLoaded, setNoteLoaded] = useState(false);
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
  const [isBlocked, setIsBlocked] = useState(false);
  const [amBlocked, setAmBlocked] = useState(false);
  const [isMutedUser, setIsMutedUser] = useState(false);
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
      setIsBlocked(!!(d as any).is_blocked); setAmBlocked(!!(d as any).am_i_blocked); setIsMutedUser(!!(d as any).is_muted);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [username, router]);

  useEffect(() => {
    if (!loading && profile && !isMine) {
      fetch(`/api/profile-notes/${profile.username}`, { credentials: "include" })
        .then(r => r.json()).then(d => { setProfileNote(d.content || ""); setNoteLoaded(true); })
        .catch(() => setNoteLoaded(true));
    }
  }, [loading, profile, isMine]);

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
      {profile.header && <div className="profile-header-banner"><img src={profile.header} alt="" /></div>}
      <div className="profile-header">
        <div className="profile-info">
          <div className="profile-avatar-col">
            <Avatar user={profile} className="profile-avatar" />
            {!isMine && (
              <button onClick={toggleFollow} className={`btn btn-small btn-follow ${isFollowing ? "btn-outline" : isFollowPending ? "btn-outline" : "btn-primary"} btn-follow-fixed`}>
                {isFollowing ? "언팔로우" : isFollowPending ? "요청됨" : "팔로우"}
              </button>
            )}
          </div>
          <div className="profile-info-relative">
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
                {!isMine && (
                  <div className="profile-corner-mute-block" style={{ display: "flex", gap: 4, marginTop: 6 }}>
                    {isMutedUser ? (
                      <button className="action-btn btn-action-sm" style={{ color: "var(--danger)", fontSize: "0.75em" }}
                        onClick={async (e) => {
                          e.preventDefault();
                          await fetch(`/api/mutes/users/${profile.id}`, { method: "DELETE", credentials: "include" });
                          setIsMutedUser(false);
                        }}>
                        <Icon name="mute" size={13} /> 뮤트됨
                      </button>
                    ) : (
                      <button className="action-btn btn-action-sm" style={{ fontSize: "0.75em" }}
                        onClick={(e) => { e.preventDefault(); setMuteDuration(0); setMuteHideNotif(false); setShowMuteModal(true); }}>
                        <Icon name="mute" size={13} /> 뮤트
                      </button>
                    )}
                    {isBlocked ? (
                      <button className="action-btn btn-action-sm" style={{ color: "var(--danger)", fontSize: "0.75em" }}
                        onClick={async (e) => {
                          e.preventDefault();
                          await fetch(`/api/blocks/users/${profile.id}`, { method: "DELETE", credentials: "include" });
                          setIsBlocked(false);
                        }}>
                        <Icon name="block" size={13} /> 블락됨
                      </button>
                    ) : (
                      <button className="action-btn btn-action-sm" style={{ fontSize: "0.75em" }}
                        onClick={(e) => { e.preventDefault(); setShowBlockConfirm(true); }}>
                        <Icon name="block" size={13} /> 블락
                      </button>
                    )}
                  </div>
                )}
              </div>
            <h2>{profile.display_name} {profile.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.7em", verticalAlign: "middle", color: "var(--text-muted)" }} />} {(profile.role === "admin" || profile.role === "moderator" || profile.role === "owner") && (isMine || (profile as any).show_badge) && <Icon name={profile.role === "owner" ? "books_solid" : "shield_filled"} style={{ color: profile.role === "owner" ? "var(--accent)" : profile.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.75em", verticalAlign: "middle", marginLeft: 3 }} title={profile.role === "owner" ? "오너" : profile.role === "admin" ? "관리자" : "조율자"} />}{(profile as any).is_deceased && <span className="deceased-badge"><svg viewBox="0 0 24 24" width="11" height="11" fill="#e8a0bf" stroke="#e8a0bf" stroke-width="0.5" style={{ verticalAlign: "middle", marginRight: 1 }}><circle cx="9" cy="8" r="2.8"/><circle cx="15" cy="8" r="2.8"/><circle cx="12" cy="5.5" r="2.8"/><path d="M6 12c2 3 4 5 6 8 2-3 4-5 6-8"/></svg> 당신을 만나고 싶습니다</span>}</h2>
            <p className="profile-username">@{profile.display_handle || profile.username}</p>
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
            {(profile as any).custom_fields?.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
                {(profile as any).custom_fields.map((f: { label: string; value: string }, i: number) => (
                  <div key={i} style={{ fontSize: "0.85em", color: "var(--text-secondary)" }}>
                    <span style={{ fontWeight: 600, marginRight: 4 }}>{f.label}</span>
                    {f.value.startsWith("http") ? <a href={f.value} target="_blank" rel="noopener" style={{ color: "var(--accent)" }}>{f.value}</a> : <span>{f.value}</span>}
                  </div>
                ))}
              </div>
            )}
            {(profile as any).profile_hashtags?.length > 0 && (
              <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
                {(profile as any).profile_hashtags.map((tag: string, i: number) => (
                  <Link key={i} href={`/explore?q=%23${encodeURIComponent(tag)}&author=${profile.username}`} style={{ display: "inline-flex", padding: "2px 8px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 10, fontSize: "0.82em", color: "var(--accent)", textDecoration: "none" }}>
                    #{tag}
                  </Link>
                ))}
              </div>
            )}
            <div className="profile-bottom-actions">
              {!isMine && profileNote && !showNote && (
                <span className="profile-note-text">{profileNote}</span>
              )}
              <div className="profile-action-btns">
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
                    <button className="action-btn btn-action-sm" onClick={() => setShowNote(!showNote)}>
                      <Icon name="edit" /> 메모
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      {!isMine && noteLoaded && showNote && (
        <div className="profile-note-card">
          <textarea value={profileNote} onChange={e => setProfileNote(e.target.value)} rows={2} className="cw-input profile-note-textarea" placeholder="이 사용자에 대한 메모..." />
          <div className="profile-note-actions">
            <button onClick={async () => {
              const form = new FormData(); form.append("content", profileNote);
              await fetch(`/api/profile-notes/${profile.username}`, { method: "POST", credentials: "include", body: form });
            }} className="btn btn-primary btn-small text-xs">메모 저장</button>
          </div>
        </div>
      )}
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
      {showBlockConfirm && (
        <ConfirmModal
          message={`@${profile.username} 님을 블락하시겠습니까? 블락하면 서로를 볼 수 없습니다.`}
          onConfirm={async () => {
            await fetch(`/api/blocks/users/${profile.id}`, { method: "POST", credentials: "include" });
            (profile as any).is_blocked = true;
            setProfile({ ...profile } as any);
            setShowBlockConfirm(false);
          }}
          onCancel={() => setShowBlockConfirm(false)}
        />
      )}
      {showMuteModal && (
        <div className="reply-modal-backdrop active" onClick={() => setShowMuteModal(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 360 }}>
            <button className="reply-modal-close" onClick={() => setShowMuteModal(false)}>×</button>
            <h3>@${profile.username} 님 뮤트</h3>
            <div className="form-group" style={{ marginTop: 12 }}>
              <label>뮤트 기간</label>
              <select value={muteDuration} onChange={(e) => setMuteDuration(Number(e.target.value))} className="cw-input">
                <option value={0}>영구</option>
                <option value={86400}>1일</option>
                <option value={259200}>3일</option>
                <option value={604800}>1주일</option>
                <option value={2592000}>1개월</option>
                <option value={7776000}>3개월</option>
              </select>
            </div>
            <div className="form-group">
              <label className="text-sm flex-center" style={{ gap: 6, cursor: "pointer", justifyContent: "flex-start" }}>
                <input type="checkbox" checked={muteHideNotif} onChange={(e) => setMuteHideNotif(e.target.checked)} />
                알림창에서도 숨기기
              </label>
            </div>
            <div className="form-actions">
              <button onClick={async () => {
                const form = new FormData();
                form.append("duration", String(muteDuration));
                form.append("hide_notifications", muteHideNotif ? "true" : "false");
                await fetch(`/api/mutes/users/${profile.id}`, { method: "POST", credentials: "include", body: form });
                (profile as any).is_muted = true;
                setProfile({ ...profile } as any);
                setShowMuteModal(false);
              }} className="btn btn-primary">뮤트</button>
              <button onClick={() => setShowMuteModal(false)} className="btn btn-outline">취소</button>
            </div>
          </div>
        </div>
      )}
      {amBlocked || isBlocked ? (
        <>
          <div className="profile-stats">
            <span className="profile-stat disabled"><strong>0</strong> 게시글</span>
            <span className="profile-stat disabled"><strong>0</strong> 시리즈</span>
            <span className="profile-stat disabled"><strong>0</strong> 팔로잉</span>
            <span className="profile-stat disabled"><strong>0</strong> 팔로워</span>
          </div>
          <div className="empty-state">{isBlocked ? "차단한 유저입니다" : "상대방이 당신을 차단했습니다"}</div>
        </>
      ) : (
      <>
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
                <div className="cover-fallback cover-fallback-sm">
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
      </>)}
    </>
  );
}
