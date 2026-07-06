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
  const [showChangeEmail, setShowChangeEmail] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [showChangeRole, setShowChangeRole] = useState(false);
  const [newRole, setNewRole] = useState("user");
  const [msg, setMsg] = useState("");

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

  const act = async (path: string, body?: Record<string, string>) => {
    const form = new FormData();
    if (body) for (const [k, v] of Object.entries(body)) form.append(k, v);
    const res = await fetch(path, { method: "POST", credentials: "include", body: form });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) { alert(d.detail || "실패"); return; }
    if (d.new_password) setMsg(`임시 비밀번호: ${d.new_password}`);
    load();
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!u) return <div className="empty-state">사용자를 찾을 수 없습니다.</div>;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <div className="admin-tabs" style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <Link href="/admin" className="btn btn-outline btn-small">대시보드</Link>
        <Link href="/admin/users" className="btn btn-outline btn-small">유저 관리</Link>
        <Link href="/admin/emojis" className="btn btn-outline btn-small">커스텀 이모지</Link>
      </div>

      {msg && <div className="empty-state" style={{ background: "var(--accent)", color: "#fff", padding: "10px 16px", borderRadius: 8, marginBottom: 12 }}>{msg}</div>}

      {/* Profile card */}
      <div style={{ display: "flex", gap: 20, padding: 20, background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 12, marginBottom: 20 }}>
        <div style={{ width: 72, height: 72, borderRadius: 12, background: `hsl(${hashStr(u.username)}, 35%, 45%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "2em", fontWeight: "bold", flexShrink: 0, position: "relative" }}>
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
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            {u.avatar && <button onClick={() => act(`/api/admin/users/${u.id}/remove-avatar`)} className="btn btn-small btn-outline">프로필 사진 삭제</button>}
          </div>
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
            <div style={{ fontSize: "1.4em", fontWeight: 700, marginTop: 4, color: c.label === "정지" ? "var(--danger)" : "var(--text-primary)" }}>{c.value}</div>
            <div style={{ fontSize: "0.8em", color: "var(--text-muted)" }}>{c.label}</div>
          </div>
        ))}
      </div>

      {/* Detail table */}
      <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", marginBottom: 20 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9em" }}>
          <tbody>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", width: 160, fontWeight: 600 }}>이메일</td>
              <td style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.email_domain ? `${u.username}@${u.email_domain}` : "-"}</td>
              <td style={{ padding: "10px 16px", width: 120 }}>
                <button onClick={() => setShowChangeEmail(!showChangeEmail)} className="btn btn-small btn-outline" style={{ fontSize: "0.8em" }}>변경</button>
              </td>
            </tr>
            {showChangeEmail && (
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td colSpan={3} style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="new@example.com" className="cw-input" style={{ flex: 1 }} />
                    <button onClick={() => { act(`/api/admin/users/${u.id}/change-email`, { email: newEmail }); setShowChangeEmail(false); }} className="btn btn-primary btn-small">저장</button>
                  </div>
                </td>
              </tr>
            )}
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>이메일 인증</td>
              <td style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.email_verified ? "완료" : "미인증"}</td>
              <td style={{ padding: "10px 16px" }}>
                {!u.email_verified && <button onClick={() => act(`/api/admin/users/${u.id}/verify-email`)} className="btn btn-small btn-outline" style={{ fontSize: "0.8em" }}>인증 처리</button>}
              </td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>역할</td>
              <td style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.role === "admin" ? "관리자" : u.role === "moderator" ? "조율자" : "유저"}</td>
              <td style={{ padding: "10px 16px" }}>
                {me?.role === "admin" && <button onClick={() => setShowChangeRole(!showChangeRole)} className="btn btn-small btn-outline" style={{ fontSize: "0.8em" }}>변경</button>}
              </td>
            </tr>
            {showChangeRole && (
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td colSpan={3} style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <select value={newRole} onChange={e => setNewRole(e.target.value)} className="cw-input">
                      <option value="user">유저</option><option value="moderator">조율자</option><option value="admin">관리자</option>
                    </select>
                    <button onClick={() => { act(`/api/admin/users/${u.id}/change-role`, { role: newRole }); setShowChangeRole(false); }} className="btn btn-primary btn-small">저장</button>
                  </div>
                </td>
              </tr>
            )}
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>공개 설정</td>
              <td colSpan={2} style={{ padding: "10px 16px", color: "var(--text-primary)" }}>
                {{ public: "공개", home: "홈", followers: "팔로워", mention: "멘션" }[u.default_visibility] || u.default_visibility}
              </td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>팔로우 수동 승인</td>
              <td colSpan={2} style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.is_locked ? "켜짐" : "꺼짐"}</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>가입일</td>
              <td colSpan={2} style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.created_at ? new Date(u.created_at).toLocaleString("ko-KR") : "-"}</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>최근 활동</td>
              <td colSpan={2} style={{ padding: "10px 16px", color: "var(--text-primary)" }}>{u.last_active ? new Date(u.last_active).toLocaleString("ko-KR") : "-"}</td>
            </tr>
            {u.recent_ips.length > 0 && (
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontWeight: 600 }}>최근 IP</td>
                <td colSpan={2} style={{ padding: "10px 16px", color: "var(--text-primary)", fontFamily: "monospace", fontSize: "0.85em" }}>{u.recent_ips.join(", ")}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button onClick={() => act(`/api/admin/users/${u.id}/reset-password`)} className="btn btn-small" style={{ border: "1px solid var(--border)" }}>암호 초기화</button>
        <button onClick={async () => {
          const form = new FormData(); form.append("user_ids", String(u.id));
          const path = u.is_suspended ? "/api/admin/users/unsuspend" : "/api/admin/users/suspend";
          const res = await fetch(path, { method: "POST", credentials: "include", body: form });
          if (res.ok) load(); else alert("실패");
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
