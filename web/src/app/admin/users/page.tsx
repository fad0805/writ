"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import { User } from "@/lib/api";

export default function AdminUsersPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    fetch("/api/admin/users", { credentials: "include" })
      .then(r => r.json()).then(d => { setUsers(d.users); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>

      <div className="admin-tabs" style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <Link href="/admin" className="btn btn-outline btn-small">대시보드</Link>
        <Link href="/admin/users" className="btn btn-primary btn-small">유저 관리</Link>
        <Link href="/admin/emojis" className="btn btn-outline btn-small">커스텀 이모지</Link>
      </div>

      {loading ? (
        <div className="empty-state">로딩 중...</div>
      ) : users.length === 0 ? (
        <div className="empty-state">사용자가 없습니다.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {users.map((u) => (
            <div key={u.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: `hsl(${hashStr(u.username)}, 35%, 45%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", fontSize: "0.9em", flexShrink: 0 }}>
                {(u.display_name || u.username)[0]}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                  {u.display_name}
                  {u.role === "admin" && <Icon name="shield_filled" style={{ color: "#27ae60", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 4 }} title="관리자" />}
                  {u.role === "moderator" && <Icon name="shield_filled" style={{ color: "#cc8800", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 4 }} title="조율자" />}
                </div>
                <div style={{ fontSize: "0.85em", color: "var(--text-muted)" }}>@{u.username} · 가입일 {new Date((u as any).created_at || Date.now()).toLocaleDateString("ko-KR")}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h);
  return ((h % 360) + 360) % 360;
}
