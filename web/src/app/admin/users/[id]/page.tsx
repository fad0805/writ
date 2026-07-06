"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";

interface UserDetail {
  id: number; username: string; display_name: string; avatar: string;
  role: string; is_suspended?: boolean; is_locked?: boolean;
  post_count: number; follower_count: number; following_count: number; novels_count: number;
  last_active: string; email_domain: string; recent_ips: string[];
  email_verified?: boolean; summary: string;
  default_visibility: string; is_remote: boolean;
  created_at: string;
}

export default function AdminUserDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user: me, loading: authLoading } = useAuth();
  const [u, setU] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetch(`/api/admin/users/${params.id}`, { credentials: "include" })
      .then(r => r.json()).then(d => { setU(d); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    if (!authLoading && me?.role !== "admin" && me?.role !== "moderator")
      router.push("/timeline/home");
  }, [me, authLoading, router]);

  useEffect(() => { if (!authLoading) load(); }, [authLoading, params.id]);

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!u) return <div className="empty-state">사용자를 찾을 수 없습니다.</div>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>

      <div className="admin-tabs" style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <Link href="/admin" className="btn btn-outline btn-small">대시보드</Link>
        <Link href="/admin/users" className="btn btn-outline btn-small">유저 관리</Link>
        <Link href="/admin/emojis" className="btn btn-outline btn-small">커스텀 이모지</Link>
      </div>

      {/* Profile card */}
      <div style={{ display: "flex", gap: 20, padding: 20, background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 12, marginBottom: 20 }}>
        <div style={{ width: 72, height: 72, borderRadius: 12, background: `hsl(${hashStr(u.username)}, 35%, 45%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "2em", fontWeight: "bold", flexShrink: 0 }}>
          {(u.display_name || u.username)[0]}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: "1.1em", color: "var(--text-primary)" }}>
            {u.display_name}
            {u.role === "admin" && <Icon name="shield_filled" style={{ color: "#27ae60", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 4 }} title="관리자" />}
            {u.role === "moderator" && <Icon name="shield_filled" style={{ color: "#cc8800", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 4 }} title="조율자" />}
          </div>
          <div style={{ color: "var(--text-muted)" }}>@{u.username}</div>
          {u.summary && <div style={{ marginTop: 6, fontSize: "0.9em", color: "var(--text-secondary)" }}>{u.summary}</div>}
        </div>
      </div>

      {/* Counters */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, marginBottom: 20 }}>
        {[
          { label: "게시물", value: u.post_count, icon: "globe" },
          { label: "팔로워", value: u.follower_count, icon: "user" },
          { label: "팔로잉", value: u.following_count, icon: "user" },
          { label: "시리즈", value: u.novels_count, icon: "book" },
          { label: "상태", value: u.is_suspended ? "정지" : "활성", icon: u.is_suspended ? "block" : "check" },
          { label: "역할", value: u.role === "admin" ? "관리자" : u.role === "moderator" ? "조율자" : "유저", icon: "shield" },
        ].map((c, i) => (
          <div key={i} style={{ padding: 14, background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, textAlign: "center" }}>
            <Icon name={c.icon} size={20} />
            <div style={{ fontSize: "1.4em", fontWeight: 700, marginTop: 4 }}>{c.value}</div>
            <div style={{ fontSize: "0.8em", color: "var(--text-muted)" }}>{c.label}</div>
          </div>
        ))}
      </div>

      {/* Detail table */}
      <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9em" }}>
          <tbody>
            {[
              ["이메일", u.username.includes("@") ? "-" : (u.email_domain ? `${u.username}@${u.email_domain}` : "-")],
              ["이메일 인증", u.email_verified ? "완료" : "미인증"],
              ["공개 설정", { public: "공개", home: "홈", followers: "팔로워", mention: "멘션" }[u.default_visibility] || u.default_visibility],
              ["팔로우 수동 승인", u.is_locked ? "켜짐" : "꺼짐"],
              ["가입일", u.created_at ? new Date(u.created_at).toLocaleString("ko-KR") : "-"],
              ["최근 활동", u.last_active ? new Date(u.last_active).toLocaleString("ko-KR") : "-"],
              ...u.recent_ips.slice(0, 5).map((ip, i) => [`최근 IP ${i + 1}`, ip]),
            ].filter(Boolean).map(([label, value], i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", width: 160, fontWeight: 600 }}>{label}</td>
                <td style={{ padding: "10px 16px", color: "var(--text-primary)", fontFamily: typeof value === "string" && value.includes(".") ? "monospace" : "inherit" }}>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
        <button onClick={async () => {
          await fetch(`/api/admin/users/suspend`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ user_ids: String(u.id) }) });
          load();
        }} className="btn btn-small" style={{ background: u.is_suspended ? "var(--accent)" : "var(--danger)", color: "#fff", border: "none" }}>
          {u.is_suspended ? "정지 해제" : "정지"}
        </button>
        <button onClick={() => router.push(`/@${u.username}`)} className="btn btn-small btn-outline">프로필 보기</button>
      </div>
    </>
  );
}

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h);
  return ((h % 360) + 360) % 360;
}
