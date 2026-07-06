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
  is_sensitive?: boolean; moderation_note?: string;
  moderation_history?: { id: number; action: string; created_at: string; by: { display_name: string; username: string } | null; meta: { action?: string; message?: string } }[];
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
  const [noteText, setNoteText] = useState("");
  const [showModerate, setShowModerate] = useState(false);
  const [modAction, setModAction] = useState("warning");
  const [modMessage, setModMessage] = useState("");
  const [modEmail, setModEmail] = useState(false);

  const load = () => {
    fetch(`/api/admin/users/${params.id}`, { credentials: "include" })
      .then(r => r.json()).then(d => { setU(d); setNoteText(d.moderation_note || ""); setLoading(false); })
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

      {/* Moderation history */}
      {u.moderation_history && u.moderation_history.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, color: "var(--text-muted)", fontSize: "0.85em", fontWeight: 600 }}>중재 기록</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {u.moderation_history.map((h) => {
              const actNames: Record<string, string> = { warning: "경고", freeze: "동결", sensitive: "민감 처리", limit: "제한", suspend: "정지", unsuspend: "정지 해제" };
              const actName = actNames[h.meta?.action || ""] || h.meta?.action || "중재";
              return (
                <div key={h.id} style={{ fontSize: "0.85em", padding: "10px 14px", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: h.meta?.message ? 6 : 0 }}>
                    <span>
                      <span style={{ fontWeight: 600, color: "var(--danger)" }}>{actName}</span>
                      <span style={{ color: "var(--text-muted)" }}> by </span>
                      <span style={{ color: "var(--text-primary)" }}>{h.by?.display_name || h.by?.username || "알 수 없음"}</span>
                    </span>
                    <span style={{ color: "var(--text-dim)", fontSize: "0.85em" }}>{h.created_at ? new Date(h.created_at).toLocaleString("ko-KR") : ""}</span>
                  </div>
                  {h.meta?.message && <div style={{ padding: "6px 10px", background: "var(--bg-tertiary)", borderRadius: 4, fontSize: "0.9em", color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>{h.meta.message}</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Moderation note */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ display: "block", marginBottom: 4, color: "var(--text-muted)", fontSize: "0.85em", fontWeight: 600 }}>참고사항</label>
        <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={3} className="cw-input" style={{ width: "100%", resize: "vertical" }} placeholder="관리자 참고용 메모..." />
        <div style={{ display: "flex", gap: 8, marginTop: 4, alignItems: "center" }}>
          <button onClick={async () => {
            const form = new FormData(); form.append("note", noteText);
            const res = await fetch(`/api/admin/users/${u.id}/note`, { method: "POST", credentials: "include", body: form });
            if (res.ok) alert("저장됨");
          }} className="btn btn-primary btn-small">메모 저장</button>
          <div style={{ flex: 1 }} />
          <button onClick={() => setShowModerate(true)} className="btn btn-small" style={{ background: "var(--danger)", color: "#fff", border: "none" }}>중재</button>
          {u.is_suspended && (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "unsuspend");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">정지 해제</button>
          )}
          <button onClick={() => act(`/api/admin/users/${u.id}/reset-password`)} className="btn btn-small" style={{ border: "1px solid var(--border)" }}>암호 초기화</button>
          <button onClick={() => router.push(`/@${u.username}`)} className="btn btn-small btn-outline">프로필 보기</button>
        </div>
      </div>

      {showModerate && (
        <div className="reply-modal-backdrop active" onClick={() => setShowModerate(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <button className="reply-modal-close" onClick={() => setShowModerate(false)}>×</button>
            <h3>중재</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div>
                <label style={{ display: "block", marginBottom: 4, color: "var(--text-muted)", fontSize: "0.85em", fontWeight: 600 }}>조치</label>
                <select value={modAction} onChange={e => setModAction(e.target.value)} className="cw-input" style={{ width: "100%" }}>
                  <option value="warning">경고 — 어떤 동작도 하지 않고 사용자에게 경고를 보냅니다</option>
                  <option value="freeze">동결 — 계정 사용을 막지만 게시물은 유지됩니다</option>
                  <option value="sensitive">민감함 — 모든 미디어를 민감함으로 강제 설정합니다</option>
                  <option value="limit">제한 — 공개 게시물 작성 제한, 팔로우하지 않는 사람에게 숨깁니다</option>
                  <option value="suspend">정지 — 모든 상호작용을 차단하고 모든 내용을 삭제합니다</option>
                </select>
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 4, color: "var(--text-muted)", fontSize: "0.85em", fontWeight: 600 }}>경고 메세지</label>
                <textarea value={modMessage} onChange={e => setModMessage(e.target.value)} rows={4} className="cw-input" style={{ width: "100%", resize: "vertical" }} placeholder="사용자에게 보낼 경고 메세지를 입력하세요..." />
              </div>
              <div>
                <label style={{ fontSize: "0.85em", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                  <input type="checkbox" checked={modEmail} onChange={e => setModEmail(e.target.checked)} />
                  이메일로 알림 보내기
                </label>
              </div>
              <div className="form-actions">
                <button onClick={async () => {
                  const form = new FormData();
                  form.append("action", modAction);
                  form.append("message", modMessage);
                  if (modEmail) form.append("send_email", "true");
                  const res = await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
                  if (res.ok) { load(); setShowModerate(false); setMsg("조치가 적용되었습니다."); }
                  else alert("실패");
                }} className="btn btn-primary">적용</button>
                <button onClick={() => setShowModerate(false)} className="btn btn-outline">취소</button>
              </div>
            </div>
          </div>
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
