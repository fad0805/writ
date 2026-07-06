"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import { User } from "@/lib/api";

type AdminUser = User & {
  created_at: string;
  post_count: number;
  follower_count: number;
  last_active: string;
  email_domain: string;
  recent_ips: string[];
};

function timeAgo(t: string): string {
  if (!t) return "";
  const diff = Date.now() - new Date(t).getTime();
  const days = Math.floor(diff / 86400000);
  if (days < 0) return "";
  if (days === 0) return "오늘";
  if (days === 1) return "1일 전";
  if (days < 7) return `${days}일 전`;
  return "";
}

export default function AdminUsersPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
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

  const toggleAll = () => {
    if (selected.size === users.length) setSelected(new Set());
    else setSelected(new Set(users.map(u => u.id)));
  };

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

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
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85em" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                <th style={{ padding: "8px 10px", textAlign: "left", width: 36 }}>
                  <input type="checkbox" checked={selected.size === users.length && users.length > 0} onChange={toggleAll} />
                </th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>사용자</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>게시물</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>팔로워</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>최근 활동</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>이메일 도메인</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>최근 IP</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid var(--border)", background: selected.has(u.id) ? "var(--card-hover)" : "transparent" }}>
                  <td style={{ padding: "10px" }}>
                    <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} />
                  </td>
                  <td style={{ padding: "10px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ width: 32, height: 32, borderRadius: 6, background: `hsl(${hashStr(u.username)}, 35%, 45%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", fontSize: "0.85em", flexShrink: 0 }}>
                        {(u.display_name || u.username)[0]}
                      </div>
                      <div>
                        <div style={{ fontWeight: 600, color: "var(--text-primary)", whiteSpace: "nowrap" }}>
                          {u.display_name}
                          {u.role === "admin" && <Icon name="shield_filled" style={{ color: "#27ae60", fontSize: "0.6em", verticalAlign: "middle", marginLeft: 3 }} title="관리자" />}
                          {u.role === "moderator" && <Icon name="shield_filled" style={{ color: "#cc8800", fontSize: "0.6em", verticalAlign: "middle", marginLeft: 3 }} title="조율자" />}
                        </div>
                        <div style={{ fontSize: "0.85em", color: "var(--text-dim)" }}>@{u.username}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{u.post_count}</td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{u.follower_count}</td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{timeAgo(u.last_active) || "-"}</td>
                  <td style={{ padding: "10px", color: "var(--text-dim)", fontSize: "0.9em" }}>{u.email_domain || "-"}</td>
                  <td style={{ padding: "10px", color: "var(--text-dim)", fontSize: "0.8em", fontFamily: "monospace" }}>{(u.recent_ips || []).join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
