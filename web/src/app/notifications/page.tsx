"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, NotificationData, User } from "@/lib/api";
import Link from "next/link";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import Avatar from "@/components/Avatar";
import DirectUserCard from "@/components/DirectUserCard";
import InfiniteScroll from "@/components/InfiniteScroll";
import { getCustomEmojis, renderCustomEmojis, renderReaction, CustomEmoji } from "@/lib/emojis";
import { sanitizeName } from "@/lib/sanitize";

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
  poll_ended: "chart",
};

const TYPE_NAMES: Record<string, string> = { post: "게시글", novel: "시리즈", episode: "에피소드" };
const ACTION_NAMES: Record<string, string> = { warning: "경고", freeze: "동결", sensitive: "민감 처리", limit: "제한", suspend: "정지", unsuspend: "정지 해제" };

interface NotificationMeta {
  reaction?: string;
  novel_title?: string;
  type?: string;
  target_type?: string;
  target_label?: string;
  action?: string;
  report_id?: number;
  novel_id?: number;
  episode_id?: number;
  target_author?: string;
  target_id?: number;
  reason?: string;
  message?: string;
}

const mergeEmojis = (base: CustomEmoji[], extra?: CustomEmoji[]): CustomEmoji[] => {
  const map = new Map((base || []).map((e) => [e.keyword, e]));
  for (const e of extra || []) {
    if (e && e.keyword && e.url && !map.has(e.keyword)) map.set(e.keyword, e);
  }
  return Array.from(map.values());
};

const typeText = (t: string, meta?: NotificationMeta, emojiMap?: CustomEmoji[]) => {
  if (t === "follow") return "님이 회원님을 팔로우했습니다";
  if (t === "follow_request") return "님이 회원님을 팔로우 요청했습니다";
  if (t === "like") {
    const reaction = meta?.reaction;
    if (reaction) {
      const rendered = sanitizeName(renderReaction(reaction, emojiMap || []));
      return <span>님이 <span dangerouslySetInnerHTML={{ __html: rendered }} /> 리액션했습니다</span>;
    }
    return "님이 회원님의 글을 즐겨찾기했습니다";
  }
  if (t === "boost") return "님이 회원님의 글을 부스트했습니다";
  if (t === "reply" || t === "mention") return "님이 회원님을 언급했습니다";
  if (t === "post") return "님이 새 글을 작성했습니다";
  if (t === "new_episode") {
    if (meta) return `님이 시리즈 "${meta.novel_title}"에 새 에피소드를 작성했습니다`;
    return "님이 새 에피소드를 작성했습니다";
  }
  if (t === "moderation") {
    if (meta?.type === "report") return `님이 ${TYPE_NAMES[meta.target_type || ""] || meta.target_type}을(를) 신고했습니다`;
    if (meta?.type === "new_user") return `님이 가입했습니다`;
    const act = ACTION_NAMES[meta?.action || ""] || meta?.action || "중재";
    return `계정에 ${act} 조치가 적용되었습니다.`;
  }
  return "";
};

const fmtTime = (t: string | null) => {
  if (!t) return "";
  const d = new Date(t);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

const DEFAULT_ICON_COLOR = "var(--text-muted)";

export default function NotificationsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, router]);

  const [notifs, setNotifs] = useState<NotificationData[]>([]);
  const [directGroups, setDirectGroups] = useState<DirectUserData[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const offsetRef = useRef(20);
  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  const touchStartX = useRef(0);

  useEffect(() => {
    const h = (e: TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
    document.addEventListener("touchstart", h, { passive: true });
    return () => document.removeEventListener("touchstart", h);
  }, []);

  useEffect(() => {
    const h = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 100) {
        const idx = FILTERS.findIndex((f) => f.value === filter);
        if (dx > 0 && idx > 0) setFilter(FILTERS[idx - 1].value);
        else if (dx < 0 && idx < FILTERS.length - 1) setFilter(FILTERS[idx + 1].value);
      }
    };
    document.addEventListener("touchend", h, { passive: true });
    return () => document.removeEventListener("touchend", h);
  }, [filter]);

  useEffect(() => {
    let id: ReturnType<typeof setTimeout> | undefined;
    try {
      const saved = sessionStorage.getItem("notif_filter");
      if (saved) {
        sessionStorage.removeItem("notif_filter");
        id = setTimeout(() => setFilter(saved), 0);
      }
    } catch {}
    return () => { if (id) clearTimeout(id); };
  }, []);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore || !user) return;
    setLoadingMore(true);
    try {
      const myUser = user.id;
      const currentOffset = offsetRef.current;
      const data = await api.getNotifications(filter || undefined, 5, currentOffset);
      if (user.id !== myUser) return;
      setNotifs((prev) => { const merged = [...prev, ...data.notifications]; if (merged.length >= 200) setHasMore(false); return merged; });
      setHasMore(data.has_more);
      offsetRef.current = currentOffset + 5;
    } catch {}
    setLoadingMore(false);
  }, [filter, hasMore, loadingMore, user]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const myUser = user.id;
    (async () => {
      try {
        if (filter === "direct") {
          const res = await fetch("/api/notifications/direct-threads", { credentials: "include" });
          const data = await res.json();
          if (user.id !== myUser) return;
          if (!cancelled) { setDirectGroups(data.users || []); setNotifs([]); }
        } else {
          const data = await api.getNotifications(filter || undefined, 20, 0);
          if (user.id !== myUser) return;
          if (!cancelled) {
            setNotifs(data.notifications);
            setHasMore(data.has_more);
            offsetRef.current = 20;
            setDirectGroups([]);
          }
        }
      } catch {}
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [filter, user]);
  useEffect(() => { window.dispatchEvent(new Event("notificationsread")); }, []);
  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);
  useEffect(() => {
    if (!user || filter === "direct") return;
    let timeout: ReturnType<typeof setTimeout>;
    const handler = () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => {
        api.getNotifications(undefined, 5, 0, false).then((data) => {
          setNotifs((prev) => {
            const existing = new Set(prev.map((n) => n.id));
            const newItems = data.notifications.filter((n) => !existing.has(n.id));
            if (newItems.length === 0) return prev;
            return [...newItems, ...prev];
          });
          setHasMore(data.has_more);
        }).catch(() => {});
      }, 300);
    };
    window.addEventListener("notifchange", handler);
    return () => { clearTimeout(timeout); window.removeEventListener("notifchange", handler); };
  }, [filter, user]);

  const handleApprove = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${username}/approve-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
    } catch {}
  }, []);

  const handleReject = useCallback(async (username: string) => {
    try {
      await fetch(`/api/users/${username}/reject-follow`, { method: "POST", credentials: "include" });
      setNotifs((prev) => prev.filter((n) => !(n.type === "follow_request" && n.from_user?.username === username)));
    } catch {}
  }, []);

  const tabsRef = useRef<HTMLDivElement>(null);
  const updateTabMask = useCallback(() => {
    const el = tabsRef.current;
    if (!el) return;
    const atStart = el.scrollLeft <= 2;
    const atEnd = el.scrollLeft >= el.scrollWidth - el.clientWidth - 2;
    const fadeSize = 20;
    const leftFade = atStart ? 0 : fadeSize;
    const rightFade = atEnd ? 0 : fadeSize;
    el.style.maskImage = `linear-gradient(to right, transparent ${leftFade}px, black ${leftFade}px, black calc(100% - ${rightFade}px), transparent calc(100% - ${rightFade}px))`;
    el.style.webkitMaskImage = el.style.maskImage;
  }, []);
  useEffect(() => {
    updateTabMask();
    window.addEventListener("resize", updateTabMask);
    return () => window.removeEventListener("resize", updateTabMask);
  }, [updateTabMask]);

  const handleMarkAllRead = useCallback(async () => {
    try {
      if (filter === "direct") {
        const res = await fetch("/api/notifications/direct-threads", { credentials: "include" });
        const data = await res.json();
        setDirectGroups(data.users || []);
      } else {
        const unreadIds = notifs.filter(n => !n.is_read).map(n => n.id);
        if (unreadIds.length === 0) return;
        await api.getNotifications(filter || undefined, 20, 0, true);
      }
      setNotifs((prev) => prev.map((n) => ({ ...n, is_read: true })));
      window.dispatchEvent(new Event("notificationsread"));
      window.dispatchEvent(new Event("notifchange"));
    } catch {}
  }, [filter, notifs]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return null;

  return (
    <>
      <div className="notif-header-row">
        <h2 className="notif-header-title">
          <Icon name="bell" /> 알림
        </h2>
        <button onClick={handleMarkAllRead} className="btn btn-small notif-mark-read" disabled={!notifs.some(n => !n.is_read)} style={{ opacity: notifs.some(n => !n.is_read) ? 1 : 0.4 }}>
          모두 읽음
        </button>
      </div>
      <div className="notif-tabs" ref={tabsRef} onScroll={updateTabMask}>
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
        {notifs.map((n) => {
          if ((n.type === "mention" || n.type === "reply") && n.post && n.from_user) {
            return <PostCard key={n.id} post={n.post} mentionBy={n.from_user} />;
          }
          return (
          <div key={n.id} className="notif-card" data-type={n.type}
            onClick={() => {
              if (n.type === "moderation" && n.metadata?.type === "report") router.push(`/admin/reports/${n.metadata.report_id}`);
              else if (n.type === "moderation" && n.metadata?.type === "new_user") router.push(`/@${n.from_user?.username}`);
              else if (n.type === "mention" && n.post?.is_dm && n.from_user) router.push(`/direct/${n.from_user.id}`);
              else if (n.type === "new_episode" && n.metadata?.novel_id && n.metadata?.episode_id) router.push(`/series/${n.metadata.novel_id}/episodes/${n.metadata.episode_id}`);
            }}
            style={{ cursor: ((n.type === "moderation" && (n.metadata?.type === "report" || n.metadata?.type === "new_user")) || (n.type === "mention" && n.post?.is_dm) || (n.type === "new_episode")) ? "pointer" : undefined }}>
            <div className="notif-icon notif-icon-dynamic" style={{ color: n.type === "like" ? "#f1c40f" : n.type === "boost" ? "var(--accent)" : n.type === "follow" ? "#4fc3f7" : n.type === "new_episode" ? "#9b59b6" : (n.type === "moderation" && n.metadata?.type === "new_user") ? "#4fc3f7" : n.type === "moderation" ? "var(--danger)" : "var(--text-muted)", borderRadius: 8, overflow: "hidden", flexShrink: 0, cursor: n.from_user ? "pointer" : undefined }} onClick={n.from_user ? (e) => { e.stopPropagation(); router.push(`/@${n.from_user!.username}`); } : undefined}>
              {n.from_user && (n.type === "like" || n.type === "boost" || n.type === "follow" || n.type === "follow_request" || n.type === "mention" || n.type === "new_episode" || n.type === "poll_ended" || (n.type === "moderation" && n.metadata?.type === "new_user") || (n.type === "moderation" && n.metadata?.type === "migrate_request")) ? (
                <Avatar user={n.from_user} style={{ width: 40, height: 40, borderRadius: 8 }} />
              ) : (
                <Icon name={(n.type === "moderation" && n.metadata?.type === "new_user") ? "user_solid" : NOTIF_ICONS[n.type] || "bell"} size={20} />
              )}
            </div>
            <div className="notif-body">
              {n.type === "moderation" && n.metadata?.type === "report" ? (
                <>
                  <Link href={`/@${n.from_user?.username}`} className="notif-from-link"><span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(n.from_user?.display_name || "", emojiMap)) }} /></Link>{" "}
                  님이 <strong>{TYPE_NAMES[n.metadata.target_type] || n.metadata.target_type}</strong>을(를) 신고했습니다
                  <div className="notif-mod-message">
                    <div style={{ fontSize: 13, marginBottom: 2 }}>
                      {n.metadata.target_author && <span>작성자: {n.metadata.target_author} · </span>}
                      대상 #{n.metadata.target_id}
                    </div>
                    {n.metadata.target_label && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 4 }}>&quot;{n.metadata.target_label}&quot;</div>}
                    <div style={{ fontSize: 13 }}>사유: {n.metadata.reason}</div>
                  </div>
                </>
              ) : n.type === "moderation" && n.metadata?.type === "new_user" ? (
                <><Link href={`/@${n.from_user?.username}`} className="notif-from-link"><span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(n.from_user?.display_name || "", emojiMap)) }} /></Link> 님이 가입했습니다</>
              ) : n.type === "moderation" && n.metadata?.type === "migrate_request" ? (
                <><Link href={`/@${n.from_user?.username}`} className="notif-from-link"><span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(n.from_user?.display_name || n.from_user?.username || "", emojiMap)) }} /></Link> 님이 계정 이전을 요청했습니다
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
                <><span className="font-bold" style={{ color: "var(--danger)" }}>{ACTION_NAMES[n.metadata?.action || ""] || n.metadata?.action || "중재"}</span> 조치가 적용되었습니다.</>
              ) : n.type === "poll_ended" ? (
                <>회원님이 참여한 투표가 끝났습니다</>
              ) : (
                <>{n.from_user && (
                  <Link href={`/@${n.from_user.username}`} className="notif-from-link">
                    <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(n.from_user.display_name, emojiMap)) }} />
                  </Link>
                )}{" "}
                {typeText(n.type, n.metadata as NotificationMeta, mergeEmojis(emojiMap, n.post?._emojis))}</>
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
        );
        })}
        </InfiniteScroll>
      )}
    </>
  );
}
