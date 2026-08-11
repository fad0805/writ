"use client";
import { useAuth } from "@/lib/auth";
import { useState, useEffect, useCallback, useRef } from "react";
import { api, NovelData, NotificationData, PostData, PollOption } from "@/lib/api";
import Icon from "./Icon";
import Link from "next/link";
import MiniPostCard from "./MiniPostCard";
import Avatar from "./Avatar";
import { useRouter } from "next/navigation";
import { renderCustomEmojis, renderReaction, useEmojiList, CustomEmoji, invalidateEmojiCache } from "@/lib/emojis";
import { sanitizeName } from "@/lib/sanitize";
import { onNotificationStream } from "@/lib/notificationStream";

const MODAL_ACTION_NAMES: Record<string, string> = {
  warning: "경고", freeze: "동결", sensitive: "민감 처리", limit: "제한", suspend: "정지",
};

export default function RightSidebar() {
  const router = useRouter();
  const { user } = useAuth();
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [notifs, setNotifs] = useState<NotificationData[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [serverInfo, setServerInfo] = useState<{ name: string; description?: string; admins: { username: string }[] } | null>(null);
  const emojiMap = useEmojiList();


  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    let debounceTimer: ReturnType<typeof setTimeout>;
    const resetId = setTimeout(() => {
      setNovels([]);
      setNotifs([]);
    }, 0);
    api.getMyNovels().then((d) => { if (!cancelled) setNovels(d.novels); }).catch(() => {});
    api.getNotifications(undefined, 10, 0).then((d) => { if (!cancelled) setNotifs(d.notifications); }).catch(() => {});
    const unsubscribe = onNotificationStream((raw) => {
      if (raw !== "refresh") return;
      invalidateEmojiCache();
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        const autoRead = document.visibilityState === "visible";
        api.getNotifications(undefined, 5, 0, autoRead).then((d) => {
          setNotifs((prev) => {
            const existing = new Set(prev.map((n) => n.id));
            const newItems = d.notifications.filter((n) => !existing.has(n.id));
            if (newItems.length === 0) return prev;
            window.dispatchEvent(new Event("notifchange"));
            return [...newItems, ...prev].slice(0, 20);
          });
          if (autoRead) window.dispatchEvent(new Event("notificationsread"));
        }).catch(() => {});
      }, 300);
    });
    return () => { cancelled = true; clearTimeout(debounceTimer); clearTimeout(resetId); unsubscribe(); };
  }, [user, refreshKey]);

  const [serverRefreshKey, setServerRefreshKey] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/server-info").then((r) => r.json()).then((d) => { if (!cancelled) setServerInfo(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [serverRefreshKey]);

  useEffect(() => {
    const handler = () => setRefreshKey((k) => k + 1);
    const serverHandler = () => setServerRefreshKey((k) => k + 1);
    window.addEventListener("novelchange", handler);
    window.addEventListener("serverchange", serverHandler);
    return () => {
      window.removeEventListener("novelchange", handler);
      window.removeEventListener("serverchange", serverHandler);
    };
  }, []);

  const handleApprove = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${encodeURIComponent(username)}/approve-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
      window.dispatchEvent(new Event("notifchange"));
    } catch {}
  }, []);

  const handleReject = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${encodeURIComponent(username)}/reject-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
      window.dispatchEvent(new Event("notifchange"));
    } catch {}
  }, []);

  const emojisFor = useCallback((post: PostData | null | undefined): CustomEmoji[] => {
    // 같은 키워드 충돌 시 이 글의 _emojis(작성자 도메인 기준)를 우선한다.
    const map = new Map<string, CustomEmoji>();
    for (const e of ((post as unknown as { _emojis?: CustomEmoji[] })?._emojis) || []) {
      if (e && e.keyword && e.url) map.set(e.keyword, { ...e, category: "remote" });
    }
    for (const e of emojiMap) {
      if (!map.has(e.keyword)) map.set(e.keyword, e);
    }
    return Array.from(map.values());
  }, [emojiMap]);

  const renderName = (name: string, post?: PostData | null | undefined) => {
    const html = renderCustomEmojis(name, emojisFor(post), 14);
    return <span dangerouslySetInnerHTML={{ __html: sanitizeName(html) }} />;
  };

  const visibleNovels = novels.slice(0, 3);
  const extraCount = novels.length - 3;
  return (
    <aside className="right-sidebar">
      {user && (<>
      <div className="widget">
        <h4><Icon name="book" /> 내 시리즈</h4>
        <div className="novel-mini-list">
          {visibleNovels.length > 0 ? visibleNovels.map((n) => (
            <Link key={n.id} href={n.number ? `/series/@${user?.username}/${n.number}` : `/series/${n.id}`} className="novel-mini-card">
              <strong>{n.title}</strong>
              <span>총 {n.episode_count}화</span>
            </Link>
          )) : (
            <p className="empty-small">연재 중인 시리즈가 없습니다.</p>
          )}
        </div>
        {extraCount > 0 && (
          <div className="more-link-wrap">
            <Link href="/series/my" className="more-link">
              더보기 +{extraCount}
            </Link>
          </div>
        )}
        <Link href="/series/new" className="btn btn-primary btn-small full-width-btn">
          + 새 시리즈 시작하기
        </Link>
      </div>
      <div style={{ flex: 1 }} />
      <div className="widget">
        <h4><Icon name="bell" /> 알림</h4>
        <div className="notif-mini-list">
          {notifs.length > 0 ? notifs.map((n) => {
            if (n.type === "vote") {
              return (
                n.post ? <MiniPostCard key={n.id} post={n.post} notifType={n.type} notifLabel={
                  n.from_user ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <Avatar user={n.from_user} style={{ width: 16, height: 16, borderRadius: 4, verticalAlign: "middle" }} />
                      <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120 }}>{renderName(n.from_user.display_name || n.from_user.username, n.post)}</strong> 님이 투표에 참여했습니다
                    </span>
                  ) : <><strong>{renderName("알 수 없음")}</strong> 님이 투표에 참여했습니다</>
                } /> : <div key={n.id} />
              );
            }

            if (n.type === "poll_ended") {
              const pollPost = n.post as unknown as PostData | undefined;
              const msg = n.metadata?.is_author ? "내 투표가 종료되었습니다" : "회원님이 참여한 투표가 종료되었습니다";
              return (
                pollPost ? <MiniPostCard key={n.id} post={pollPost} notifType={n.type} notifLabel={
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 4 }}>
                    <span>{msg}</span>
                    {n.from_user && (
                      <Link href={`/@${n.from_user.username}`} style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--text-primary)", fontWeight: 600, overflow: "hidden", minWidth: 0 }} onClick={(e) => e.stopPropagation()}>
                        <Avatar user={n.from_user} style={{ width: 16, height: 16, borderRadius: 4, flexShrink: 0 }} />
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.9em" }}>{renderName(n.from_user.display_name || n.from_user.username, pollPost)}</span>
                      </Link>
                    )}
                  </div>
                } /> : <div key={n.id} />
              );
            }

            if (n.post) return (
              <MiniPostCard key={n.id} post={n.post} notifType={n.type} notifLabel={
                (n.type === "like" || n.type === "boost" || n.type === "mention" || n.type === "reply") && n.from_user ? (
                  <span style={{ display: "inline" }}>
                    <Avatar user={n.from_user} style={{ width: 16, height: 16, borderRadius: 4, verticalAlign: "text-bottom", marginRight: 4 }} />
                    <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120, display: "inline-block", verticalAlign: "text-bottom" }}>{renderName(n.from_user.display_name || n.from_user.username, n.post)}</strong>{" "}
                    {n.type === "like" ? (n.metadata?.reaction ? <span dangerouslySetInnerHTML={{ __html: sanitizeName(`님이 ${renderReaction(n.metadata.reaction, emojisFor(n.post), 14)} 리액션했습니다`) }} /> : "님이 즐겨찾기했습니다") : n.type === "boost" ? "님이 부스트했습니다" : "님이 회원님을 언급했습니다"}
                  </span>
                ) : undefined
              } />
            );

            if (n.type === "follow" || n.type === "follow_request") {
              return (
                <Link key={n.id} href={`/@${n.from_user?.username || ""}`} className="mini-post-link" style={{ background: "var(--bg-tertiary)", cursor: "pointer" }}>
                  <div className="mini-post-avatar-box" style={{ width: 28, height: 28, borderRadius: 6, overflow: "hidden", flexShrink: 0 }}>
                    {n.from_user ? <Avatar user={n.from_user} style={{ width: 28, height: 28, borderRadius: 6 }} /> : <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "#4fc3f7", width: 28, height: 28 }}><Icon name="user_solid" size={14} /></div>}
                  </div>
                  <div className="mini-post-content">
                    <div className="mini-post-author">
                      {renderName(n.from_user?.display_name || "알 수 없음")}
                      <span className="mini-post-handle">@{n.from_user?.username}</span>
                    </div>
                    <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                      {n.type === "follow" ? "회원님을 팔로우했습니다" : "회원님을 팔로우 요청했습니다"}
                    </div>
                    {n.type === "follow_request" && n.from_user && (
                      <div className="mini-notif-btns" onClick={(e) => e.preventDefault()} style={{ display: "flex", gap: 4, marginTop: 4 }}>
                        <button onClick={() => handleApprove(n.from_user!.username)} className="btn btn-primary btn-small btn-follow">수락</button>
                        <button onClick={() => handleReject(n.from_user!.username)} className="btn btn-small btn-follow text-muted">거절</button>
                      </div>
                    )}
                  </div>
                </Link>
              );
            }

            if (n.type === "moderation") {
              if (n.metadata?.type === "new_user") {
                return (
                  <Link key={n.id} href={`/@${n.from_user?.username || ""}`} className="mini-post-link" style={{ background: "var(--bg-tertiary)", cursor: "pointer" }}>
                    <div className="mini-post-avatar-box" style={{ width: 28, height: 28, borderRadius: 6, overflow: "hidden", flexShrink: 0 }}>
                      {n.from_user ? <Avatar user={n.from_user} style={{ width: 28, height: 28, borderRadius: 6 }} /> : <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "#4fc3f7", width: 28, height: 28 }}><Icon name="user_solid" size={14} /></div>}
                    </div>
                    <div className="mini-post-content">
                      <div className="mini-post-author">
                        {renderName(n.from_user?.display_name || "알 수 없음")}
                        <span className="mini-post-handle">@{n.from_user?.username}</span>
                      </div>
                      <div className="text-sm" style={{ color: "var(--text-muted)" }}>가입했습니다</div>
                    </div>
                  </Link>
                );
              }
              if (n.metadata?.type === "report") {
                const targetName = n.metadata?.target_type || "콘텐츠";
                return (
                  <Link key={n.id} href="/admin/reports" className="mini-post-link" style={{ background: "var(--bg-tertiary)", cursor: "pointer" }}>
                    <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "var(--danger)" }}>
                      <Icon name="flag" size={14} />
                    </div>
                    <div className="mini-post-content">
                      <div className="mini-post-author">
                        {renderName(n.from_user?.display_name || "알 수 없음")}
                        <span className="mini-post-handle">@{n.from_user?.username}</span>
                      </div>
                      <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                        님이 {targetName}을(를) 신고했습니다
                      </div>
                    </div>
                  </Link>
                );
              }
              if (n.metadata?.type === "migrate_request") {
                const fromName = n.from_user?.display_name || n.from_user?.username || "알 수 없음";
                return (
                  <div key={n.id} className="mini-post-link" style={{ background: "var(--bg-tertiary)" }}>
                    <div className="mini-post-avatar-box" style={{ width: 28, height: 28, borderRadius: 6, overflow: "hidden", flexShrink: 0 }}>
                      {n.from_user ? <Avatar user={n.from_user} style={{ width: 28, height: 28, borderRadius: 6 }} /> : <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "#e74c3c", width: 28, height: 28 }}><Icon name="user_solid" size={14} /></div>}
                    </div>
                    <div className="mini-post-content">
                      <div className="text-sm" style={{ color: "var(--text)" }}>
                        <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120, display: "inline-block", verticalAlign: "middle" }}>{renderName(fromName)}</strong>
                        <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>님이 계정 이전을 요청했습니다</span>
                      </div>
                      <div className="mini-notif-btns" style={{ display: "flex", gap: 4, marginTop: 4 }}>
                        <button onClick={async () => {
                          const form = new FormData(); form.append("notification_id", String(n.id));
                          await fetch("/api/settings/migrate/approve", { method: "POST", credentials: "include", body: form });
                          setNotifs((prev) => prev.filter((x) => x.id !== n.id));
                        }} className="btn btn-primary btn-small btn-follow">수락</button>
                        <button onClick={async () => {
                          const form = new FormData(); form.append("notification_id", String(n.id));
                          await fetch("/api/settings/migrate/reject", { method: "POST", credentials: "include", body: form });
                          setNotifs((prev) => prev.filter((x) => x.id !== n.id));
                        }} className="btn btn-small btn-follow text-muted">거절</button>
                      </div>
                    </div>
                  </div>
                );
              }
              const actionName = MODAL_ACTION_NAMES[n.metadata?.action] || n.metadata?.action || "중재";
              return (
                <div key={n.id} className="mini-post-link" style={{ background: "var(--bg-tertiary)" }}>
                  <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "var(--danger)" }}>
                    <Icon name="shield_filled" size={14} />
                  </div>
                  <div className="mini-post-content">
                    <div className="text-sm">
                      <span style={{ color: "var(--danger)", fontWeight: 600 }}>{actionName}</span>{" "}
                      <span style={{ color: "var(--text-muted)" }}>조치가 적용되었습니다</span>
                    </div>
                    {n.metadata?.message && (
                      <div className="text-sm" style={{ color: "var(--text-muted)", marginTop: 2 }}>{n.metadata.message}</div>
                    )}
                  </div>
                </div>
              );
            }

            if (n.type === "new_episode") {
              return (
                <Link key={n.id} href={n.metadata?.novel_id && n.metadata?.episode_id ? `/series/${n.metadata.novel_id}/episodes/${n.metadata.episode_id}` : "#"} className="mini-post-link" style={{ background: "var(--bg-tertiary)" }}>
                  <div className="mini-post-avatar-box" style={{ width: 28, height: 28, borderRadius: 6, overflow: "hidden", flexShrink: 0 }}>
                    {n.from_user ? <Avatar user={n.from_user} style={{ width: 28, height: 28, borderRadius: 6 }} /> : <div className="mini-post-avatar-box mini-post-avatar-box-icon" style={{ color: "#9b59b6", width: 28, height: 28 }}><Icon name="book" size={14} /></div>}
                  </div>
                  <div className="mini-post-content">
                    <div className="mini-post-author">
                      {renderName(n.from_user?.display_name || "알 수 없음")}
                      <span className="mini-post-handle">@{n.from_user?.username}</span>
                    </div>
                    <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                      {n.metadata?.novel_title ? `"${n.metadata.novel_title}" 새 에피소드` : "새 에피소드"}
                    </div>
                  </div>
                </Link>
              );
            }

            return null;
          }) : <p className="empty-small p-0">알림이 없습니다.</p>}
        </div>
      </div>
      </>)}
      <div className="widget" style={{ marginTop: "auto", borderTop: "1px solid var(--border)", paddingTop: 12, marginBottom: 0 }}>
        <h4><Icon name="globe" /> 서버 정보</h4>
        {serverInfo ? (
          <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{serverInfo.name}</div>
            {serverInfo.description && <div style={{ fontSize: 12, marginBottom: 6, color: "var(--text-dim)" }}>{serverInfo.description}</div>}
            {serverInfo.admins?.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {serverInfo.admins.map((a) => (
                  <div key={a.username} style={{ marginBottom: 2 }}>
                    <Link href={`/@${a.username}`} style={{ color: "var(--accent)" }}>@{a.username}</Link>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="empty-small">로딩 중...</p>
        )}
      </div>
      <div style={{ borderTop: "1px solid var(--border)", padding: "10px 0 4px", fontSize: 12, color: "var(--text-dim)", display: "flex", gap: 12 }}>
        <Link href="/rules" style={{ color: "var(--accent)" }}>서버 규칙</Link>
        <a href="https://github.com/fad0805/writ" target="_blank" rel="noopener" style={{ color: "var(--accent)" }}>
          소스코드 (GitHub)
        </a>
      </div>
    </aside>
  );
}
