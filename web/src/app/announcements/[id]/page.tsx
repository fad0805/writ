"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";
import { Announcement, fmtAnnouncementTime } from "@/lib/announcements";

export default function AnnouncementDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [item, setItem] = useState<Announcement | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!id || !user) return;
    setLoading(true);
    fetch(`/api/announcements/${id}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        setItem(d);
        if (d) {
          fetch(`/api/announcements/${id}/read`, { method: "POST", credentials: "include" }).catch(() => {});
          window.dispatchEvent(new Event("announcementchange"));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, user]);

  if (authLoading || loading) return <p className="empty-state">로딩 중...</p>;
  if (!user) return null;
  if (!item) return <p className="empty-state">공지사항을 찾을 수 없습니다.</p>;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <Link href="/announcements" style={{ fontSize: 13, color: "var(--accent)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 16 }}>
        <Icon name="chevron_left" size={14} /> 공지사항 목록
      </Link>
      <h1 style={{ fontSize: 22, marginBottom: 8 }}><Icon name="star_filled" /> {item.title}</h1>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>
        {item.created_by ? `${item.created_by} · ` : ""}{fmtAnnouncementTime(item.created_at)}
        {(item.starts_at || item.ends_at) && (
          <span> · 노출 기간: {fmtAnnouncementTime(item.starts_at) || "무기한"} ~ {fmtAnnouncementTime(item.ends_at) || "무기한"}</span>
        )}
      </div>
      <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, padding: "20px 24px", fontSize: 15, lineHeight: 1.7, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {item.content || "내용이 없습니다."}
      </div>
    </div>
  );
}
