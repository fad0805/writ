"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";
import { Announcement, fmtAnnouncementTime } from "@/lib/announcements";

export default function AnnouncementsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, router]);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/announcements", { credentials: "include" });
      if (res.ok) {
        const d = await res.json();
        setItems(d.announcements || []);
      }
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (items.some((a) => !a.is_read)) {
      window.dispatchEvent(new Event("announcementchange"));
    }
  }, [items]);

  if (authLoading || loading) return <p className="empty-state">로딩 중...</p>;
  if (!user) return null;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ marginBottom: 8 }}><Icon name="star_filled" /> 공지사항</h1>
      <p style={{ color: "var(--text-secondary)", marginBottom: 24, fontSize: 14 }}>
        서버 운영진이 전하는 소식입니다.
      </p>
      {items.length === 0 ? (
        <p className="empty-state">현재 공지사항이 없습니다.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((a) => (
            <Link key={a.id} href={`/announcements/${a.id}`} style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", textDecoration: "none", color: "inherit", display: "block" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Icon name="star_filled" size={14} style={{ color: a.is_read ? "var(--text-muted)" : "#f1c40f" }} />
                <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title}</strong>
                {!a.is_read && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#f1c40f", flexShrink: 0 }} />}
                <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-muted)", flexShrink: 0 }}>{fmtAnnouncementTime(a.created_at)}</span>
              </div>
              {a.content && (
                <p style={{ margin: "8px 0 0", fontSize: 14, color: "var(--text-secondary)", whiteSpace: "pre-wrap", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{a.content}</p>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
