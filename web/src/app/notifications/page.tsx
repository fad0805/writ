"use client";
import { useEffect, useState } from "react";
import { api, NotificationData } from "@/lib/api";
import Link from "next/link";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";

const FILTERS = [
  { value: "", label: "전체", icon: "bell" },
  { value: "mention", label: "멘션", icon: "mention" },
  { value: "like", label: "즐겨찾기", icon: "star_filled" },
  { value: "boost", label: "재게시", icon: "refresh" },
  { value: "follow", label: "팔로우", icon: "user_solid" },
  { value: "direct", label: "다이렉트", icon: "direct" },
];

const NOTIF_ICONS: Record<string, string> = {
  follow: "user_solid",
  like: "star_filled",
  boost: "refresh",
  reply: "mention",
  mention: "mention",
  post: "bell_solid",
};

export default function NotificationsPage() {
  const [notifs, setNotifs] = useState<NotificationData[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getNotifications(filter || undefined);
      setNotifs(data.notifications);
    } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, [filter]);

  const typeText = (t: string) => {
    if (t === "follow") return "님이 회원님을 팔로우했습니다";
    if (t === "like") return "님이 회원님의 글을 즐겨찾기했습니다";
    if (t === "boost") return "님이 회원님의 글을 부스트했습니다";
    if (t === "reply" || t === "mention") return "님이 회원님을 언급했습니다";
    if (t === "post") return "님이 새 글을 작성했습니다";
    return "";
  };

  const fmtTime = (t: string | null) => {
    if (!t) return "";
    const d = new Date(t);
    return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const handleMarkAllRead = async () => {
    try {
      await api.getNotifications(filter || undefined);
      load();
    } catch {}
  };

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="bell" /> 알림
        </h2>
        <button onClick={handleMarkAllRead} className="btn btn-small" style={{ background: "var(--accent)", color: "#fff", border: "none" }}>
          모두 읽음
        </button>
      </div>
      <div className="notif-tabs">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`notif-tab ${f.value === filter ? "active" : ""}`}
          >
            <Icon name={f.icon} /> {f.label}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="empty-state">로딩 중...</p>
      ) : notifs.length === 0 ? (
        <p className="empty-state">알림이 없습니다.</p>
      ) : (
        notifs.map((n) => (
          <div key={n.id} className="notif-card" data-type={n.type}>
            <div className="notif-icon" style={{ color: n.type === "like" ? "#f1c40f" : n.type === "boost" ? "var(--accent)" : n.type === "follow" ? "#4fc3f7" : "var(--text-muted)" }}>
              <Icon name={NOTIF_ICONS[n.type] || "bell"} size={20} />
            </div>
            <div className="notif-body">
              {n.from_user && (
                <Link href={`/@${n.from_user.username}`} style={{ fontWeight: 600 }}>
                  {n.from_user.display_name}
                </Link>
              )}{" "}
              {typeText(n.type)}
              <span className="notif-time">{fmtTime(n.created_at)}</span>
              {n.post && <PostCard post={n.post} />}
            </div>
          </div>
        ))
      )}
    </>
  );
}
