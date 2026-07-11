"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, NotificationData, User } from "@/lib/api";
import Link from "next/link";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import DirectUserCard from "@/components/DirectUserCard";
import InfiniteScroll from "@/components/InfiniteScroll";

type DirectUserData = User & {
  latest_previews?: { text: string; is_me: boolean }[];
  latest_time?: string;
};

const FILTERS = [
  { value: "", label: "전체", icon: "bell" },
  { value: "mention", label: "멘션", icon: "mention" },
  { value: "like", label: "즐겨찾기", icon: "star_filled" },
  { value: "boost", label: "재게시", icon: "refresh" },
  { value: "follow", label: "팔로우", icon: "user_solid" },
  { value: "vote", label: "투표", icon: "check" },
  { value: "new_episode", label: "시리즈", icon: "book" },
  { value: "direct", label: "다이렉트", icon: "direct" },
];

const NOTIF_ICONS: Record<string, string> = {
  follow: "user_solid",
  follow_request: "user_solid",
  like: "star_filled",
  boost: "refresh",
  reply: "mention",
  mention: "mention",
  post: "bell_solid",
  moderation: "shield_filled",
  new_episode: "book",
  vote: "check",
  poll_ended: "chart",
};

export default function NotificationsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [notifs, setNotifs] = useState<NotificationData[]>([]);
  const [directGroups, setDirectGroups] = useState<DirectUserData[]>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, router]);

  useEffect(() => {
    try { const s = sessionStorage.getItem("notif_filter"); if (s) { sessionStorage.removeItem("notif_filter"); setFilter(s); } } catch {}
  }, []);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(20);
  const isFirstRender = useRef(true);

  if (authLoading || !user) return <div className="empty-state">{authLoading ? "로딩 중..." : "로그인이 필요합니다"}</div>;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (filter === "direct") {
        const res = await fetch("/api/notifications/direct-threads", { credentials: "include" });
        const data = await res.json();
        setDirectGroups(data.users || []);
        setNotifs([]);
        setHasMore(false);
      } else {
        const data = await api.getNotifications(filter || undefined, 20, 0);
        setNotifs(data.notifications);
        setHasMore(data.has_more);
        setOffset(20);
        setDirectGroups([]);
      }
    } catch {}
    setLoading(false);
  }, [filter]);

  const loadMore = useCallback(async () => {
    if (loading || loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const data = await api.getNotifications(filter || undefined, 10, offset);
      setNotifs((prev) => [...prev, ...data.notifications]);
      setHasMore(data.has_more);
      setOffset((prev) => prev + 10);
    } catch {}
    setLoadingMore(false);
  }, [filter, offset, hasMore, loadingMore, loading]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!loading && !authLoading && user && isFirstRender.current) {
      window.dispatchEvent(new Event("notificationsread"));
      isFirstRender.current = false;
    }
  }, [loading, authLoading, user]);

  const actionNames: Record<string, string> = {
    warning: "경고", freeze: "동결", sensitive: "민감 처리", limit: "제한", suspend: "정지", unsuspend: "정지 해제",
  };
  const targetTypeNames: Record<string, string> = {
    post: "게시글", novel: "시리즈", episode: "에피소드",
  };

  const typeText = (t: string, meta?: any) => {
    if (t === "follow") return "님이 회원님을 팔로우했습니다";
    if (t === "follow_request") return "님이 회원님을 팔로우 요청했습니다";
    if (t === "like") return "님이 회원님의 글을 즐겨찾기했습니다";
    if (t === "boost") return "님이 회원님의 글을 부스트했습니다";
    if (t === "reply" || t === "mention") return "님이 회원님을 언급했습니다";
    if (t === "post") return "님이 새 글을 작성했습니다";
    if (t === "vote") return "님이 회원님의 투표에 참여했습니다";
    if (t === "poll_ended") {
      if (meta?.is_author) return "내 투표가 종료되었습니다";
      return "참여한 투표가 종료되었습니다";
    }
    if (t === "new_episode") {
      if (meta) return `님이 시리즈 "${meta.novel_title}"에 새 에피소드를 작성했습니다`;
      return "님이 새 에피소드를 작성했습니다";
    }
    if (t === "moderation") {
      if (meta?.type === "report") return `님이 ${targetTypeNames[meta.target_type] || meta.target_type}을(를) 신고했습니다`;
      if (meta?.type === "new_user") return `님이 가입했습니다`;
      const act = actionNames[meta?.action] || meta?.action || "중재";
      return `계정에 ${act} 조치가 적용되었습니다.`;
    }
    return "";
  };

  const fmtTime = (t: string | null) => {
    if (!t) return "";
    const d = new Date(t);
    return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const handleApprove = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${encodeURIComponent(username)}/approve-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
    } catch {}
  }, []);

  const handleReject = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${encodeURIComponent(username)}/reject-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
    } catch {}
  }, []);

  const handleMarkAllRead = async () => {
    try {
      if (filter === "direct") {
        const res = await fetch("/api/notifications/direct-threads", { credentials: "include" });
        const data = await res.json();
        setDirectGroups(data.users || []);
        setNotifs([]);
      } else {
        const data = await api.getNotifications(filter || undefined, 50, 0);
        setNotifs(data.notifications);
        setDirectGroups([]);
      }
      window.dispatchEvent(new Event("notificationsread"));
      window.dispatchEvent(new Event("notifchange"));
    } catch {}
  };

  return (
    <>
      <div className="notif-header-row">
        <h2 className="notif-header-title">
          <Icon name="bell" /> 알림
        </h2>
        <button onClick={handleMarkAllRead} className="btn btn-small notif-mark-read">
          모두 읽음
        </button>
      </div>
      <div className="notif-tabs">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`notif-tab${f.value === filter ? " active" : ""}`}
          >
            <Icon name={f.icon} /> {f.label}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="empty-state">로딩 중...</p>
      ) : filter === "direct" ? (
        directGroups.length === 0 ? (
          <p className="empty-state">다이렉트 메시지가 없습니다.</p>
        ) : directGroups.map((u) => (
          <DirectUserCard key={u.id} user={u} />
        ))
      ) : notifs.length === 0 ? (
        <p className="empty-state">알림이 없습니다.</p>
      ) : (
        <InfiniteScroll hasMore={hasMore} loadingMore={loadingMore} loadMore={loadMore}>
        {notifs.map((n) => (
          <div key={n.id} className="notif-card" data-type={n.type}
            onClick={() => {
              if (n.type === "moderation" && n.metadata?.type === "report") router.push(`/admin/reports/${n.metadata.report_id}`);
              else if (n.type === "moderation" && n.metadata?.type === "new_user") router.push(`/@${n.from_user?.username}`);
              else if (n.type === "mention" && n.post?.is_dm && n.from_user) router.push(`/direct/${n.from_user.id}`);
              else if (n.type === "new_episode" && n.metadata?.novel_id && n.metadata?.episode_id) router.push(`/series/${n.metadata.novel_id}/episodes/${n.metadata.episode_id}`);
            }}
            style={{ cursor: ((n.type === "moderation" && (n.metadata?.type === "report" || n.metadata?.type === "new_user")) || (n.type === "mention" && n.post?.is_dm) || (n.type === "new_episode")) ? "pointer" : undefined }}>
            <div className="notif-icon notif-icon-dynamic" style={{ color: n.type === "like" ? "#f1c40f" : n.type === "boost" ? "var(--accent)" : n.type === "follow" ? "#4fc3f7" : n.type === "new_episode" ? "#9b59b6" : (n.type === "moderation" && n.metadata?.type === "new_user") ? "#4fc3f7" : n.type === "moderation" ? "var(--danger)" : "var(--text-muted)" }}>
              <Icon name={(n.type === "moderation" && n.metadata?.type === "new_user") ? "user_solid" : NOTIF_ICONS[n.type] || "bell"} size={20} />
            </div>
            <div className="notif-body">
              {n.type === "moderation" && n.metadata?.type === "report" ? (
                <>
                  <Link href={`/@${n.from_user?.username}`} className="notif-from-link">{n.from_user?.display_name}</Link>{" "}
                  님이 <strong>{targetTypeNames[n.metadata.target_type] || n.metadata.target_type}</strong>을(를) 신고했습니다
                  <div className="notif-mod-message">
                    <div style={{ fontSize: 13, marginBottom: 2 }}>
                      {n.metadata.target_author && <span>작성자: {n.metadata.target_author} · </span>}
                      대상 #{n.metadata.target_id}
                    </div>
                    {n.metadata.target_label && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 4 }}>"{n.metadata.target_label}"</div>}
                    <div style={{ fontSize: 13 }}>사유: {n.metadata.reason}</div>
                  </div>
                </>
              ) : n.type === "moderation" && n.metadata?.type === "new_user" ? (
                <><Link href={`/@${n.from_user?.username}`} className="notif-from-link">{n.from_user?.display_name}</Link> 님이 가입했습니다</>
              ) : n.type === "moderation" && n.metadata?.type === "migrate_request" ? (
                <><Link href={`/@${n.from_user?.username}`} className="notif-from-link">{n.from_user?.display_name || n.from_user?.username}</Link> 님이 계정 이전을 요청했습니다
                <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                  <button onClick={async () => {
                    const form = new FormData();
                    form.append("notification_id", String(n.id));
                    await fetch("/api/settings/migrate/approve", { method: "POST", credentials: "include", body: form });
                    setNotifs((prev) => prev.filter((x) => x.id !== n.id));
                    window.dispatchEvent(new Event("followchange"));
                  }} className="btn btn-primary btn-small">수락</button>
                  <button onClick={async () => {
                    const form = new FormData();
                    form.append("notification_id", String(n.id));
                    await fetch("/api/settings/migrate/reject", { method: "POST", credentials: "include", body: form });
                    setNotifs((prev) => prev.filter((x) => x.id !== n.id));
                  }} className="btn btn-small btn-outline">거절</button>
                </div></>
              ) : n.type === "moderation" ? (
                <><span className="font-bold" style={{ color: "var(--danger)" }}>{actionNames[n.metadata?.action] || n.metadata?.action || "중재"}</span> 조치가 적용되었습니다.</>
              ) : (
                <>{n.from_user && (
                  <Link href={`/@${n.from_user.username}`} className="notif-from-link">
                    {n.from_user.display_name}
                  </Link>
                )}{" "}
                {typeText(n.type, n.metadata)}</>
              )}
              <span className="notif-time">{fmtTime(n.created_at)}</span>
              {n.type === "moderation" && n.metadata?.message && n.metadata?.type !== "report" && n.metadata?.type !== "new_user" && (
                <div className="notif-mod-message">{n.metadata.message}</div>
              )}
              {n.type === "follow_request" && n.from_user && (
                <div className="notif-follow-btns">
                  <button onClick={() => handleApprove(n.from_user!.username)} className="btn btn-primary btn-small btn-follow">수락</button>
                  <button onClick={() => handleReject(n.from_user!.username)} className="btn btn-small btn-follow text-muted">거절</button>
                </div>
              )}
              {n.post && <PostCard post={n.post} readonly />}
            </div>
          </div>
        ))}
        </InfiniteScroll>
      )}
    </>
  );
}
