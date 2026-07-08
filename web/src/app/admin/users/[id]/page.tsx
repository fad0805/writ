"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

interface UserDetail {
  id: number; username: string; display_name: string; avatar: string;
  role: string; is_suspended?: boolean; is_locked?: boolean;
  post_count: number; follower_count: number; following_count: number; novels_count: number;
  last_active: string; email_domain: string; recent_ips: string[];
  email_verified?: boolean; summary: string;
  default_visibility: string; is_remote: boolean;
  created_at: string;
  is_limited?: boolean; is_frozen?: boolean; is_deceased?: boolean; is_sensitive?: boolean; moderation_note?: string;
  moderation_history?: { id: number; action: string; created_at: string; by: { display_name: string; username: string } | null; meta: { action?: string; message?: string } }[];
}

const actionLabels: Record<string, string> = {
  warning: "경고", freeze: "동결", sensitive: "민감 처리", limit: "제한", suspend: "정지",
  unsuspend: "정지 해제", unlimit: "제한 해제", unfreeze: "동결 해제", unsensitive: "민감 해제",
  deceased: "고인 설정", undeceased: "고인 해제",
  moderate: "중재", toggle_sensitive: "민감 전환",
  change_role: "권한 변경", reset_password: "비밀번호 초기화",
  admin_change_email: "이메일 강제 변경", verify_email: "이메일 인증",
  remove_avatar: "아바타 제거", set_note: "메모 설정",
  block_domain: "도메인 차단",
  delete_post: "게시글 삭제",
};

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
  const [logs, setLogs] = useState<any[]>([]);

  const load = async () => {
    const [userRes, logsRes] = await Promise.all([
      fetch(`/api/admin/users/${params.id}`, { credentials: "include" }),
      fetch(`/api/admin/logs?target_type=user&target_id=${params.id}&limit=20`, { credentials: "include" }),
    ]);
    if (userRes.ok) {
      const d = await userRes.json();
      setU(d);
      setNoteText(d.moderation_note || "");
    }
    if (logsRes.ok) {
      const d = await logsRes.json();
      setLogs(d.logs || []);
    }
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading && me?.role !== "admin" && me?.role !== "moderator" && me?.role !== "owner")
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
      <AdminNav current="users" />

      {msg && <div className="empty-state" style={{ background: "var(--accent)", color: "#fff", padding: "10px 16px", borderRadius: 8, marginBottom: 12 }}>{msg}</div>}

      {/* Profile card */}
      <div className="admin-profile-card">
        <div className="admin-profile-avatar" style={{ background: `hsl(${hashStr(u.username)}, 35%, 45%)` }}>
          {(u.display_name || u.username)[0]}
        </div>
        <div className="admin-profile-info">
          <div className="admin-profile-name">
            {u.display_name}
            {u.role === "owner" && <Icon name="books_solid" style={{ color: "var(--accent)", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 4 }} title="오너" />}
            {u.role === "admin" && <Icon name="shield_filled" style={{ color: "#27ae60", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 4 }} title="관리자" />}
            {u.role === "moderator" && <Icon name="shield_filled" style={{ color: "#cc8800", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 4 }} title="조율자" />}
          </div>
          <div className="admin-profile-username">@{u.username}</div>
          {u.summary && <div className="admin-profile-summary">{u.summary}</div>}
          <div className="admin-profile-actions">
            {u.avatar && <button onClick={() => act(`/api/admin/users/${u.id}/remove-avatar`)} className="btn btn-small btn-outline">프로필 사진 삭제</button>}
          </div>
        </div>
      </div>

      {/* Counters */}
      <div className="admin-counter-grid">
        {[
          { label: "게시물", value: u.post_count, icon: "globe" },
          { label: "팔로워", value: u.follower_count, icon: "user" },
          { label: "팔로잉", value: u.following_count, icon: "user" },
          { label: "시리즈", value: u.novels_count, icon: "book" },
          { label: "상태", value: u.is_deceased ? "고인" : u.is_suspended ? "정지" : u.is_frozen ? "동결" : u.is_limited ? "제한" : "활성", icon: u.is_deceased ? "block" : u.is_suspended ? "block" : u.is_frozen ? "block" : u.is_limited ? "block" : "check" },
          { label: "역할", value: u.role === "owner" ? "오너" : u.role === "admin" ? "관리자" : u.role === "moderator" ? "조율자" : "유저", icon: "shield" },
        ].map((c, i) => (
          <div key={i} className="admin-counter-card">
            <Icon name={c.icon} size={20} />
            <div className="admin-counter-value" style={{ color: c.label === "정지" ? "var(--danger)" : "var(--text-primary)" }}>{c.value}</div>
            <div className="admin-counter-label">{c.label}</div>
          </div>
        ))}
      </div>

      {/* Detail table */}
      <div className="admin-detail-card">
        <table className="detail-table">
          <tbody>
            <tr>
              <td className="label">이메일</td>
              <td className="value">{u.email_domain ? `${u.username}@${u.email_domain}` : "-"}</td>
              <td className="action admin-action-cell">
                <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
                  <button onClick={() => setShowChangeEmail(!showChangeEmail)} className="btn btn-small btn-outline text-xs admin-action-btn-eq">변경</button>
                  {u.email_domain && (
                    <button onClick={async () => {
                      const form = new FormData(); form.append("domain", u.email_domain!);
                      const res = await fetch("/api/admin/block-domain", { method: "POST", credentials: "include", body: form });
                      const d = await res.json().catch(() => ({}));
                      alert(res.ok ? `도메인 ${u.email_domain} 차단됨` : (d.detail || "실패"));
                    }} className="btn btn-small btn-outline text-xs admin-action-btn-eq" style={{ color: "var(--danger)" }}>도메인 차단</button>
                  )}
                </div>
              </td>
            </tr>
            {showChangeEmail && (
              <tr>
                <td colSpan={3} style={{ padding: "10px 16px" }}>
                  <div className="flex-row gap-8">
                    <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="new@example.com" className="cw-input flex-1" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { act(`/api/admin/users/${u.id}/change-email`, { email: newEmail }); setShowChangeEmail(false); } }} />
                    <button onClick={() => { act(`/api/admin/users/${u.id}/change-email`, { email: newEmail }); setShowChangeEmail(false); }} className="btn btn-primary btn-small">저장</button>
                  </div>
                </td>
              </tr>
            )}
            <tr>
              <td className="label">이메일 인증</td>
              <td className="value">{u.email_verified ? "완료" : "미인증"}</td>
              <td className="action admin-action-cell">
                {!u.email_verified && <button onClick={() => act(`/api/admin/users/${u.id}/verify-email`)} className="btn btn-small btn-outline text-xs admin-action-btn-eq">인증 처리</button>}
              </td>
            </tr>
            <tr>
              <td className="label">역할</td>
              <td className="value">{u.role === "owner" ? "오너" : u.role === "admin" ? "관리자" : u.role === "moderator" ? "조율자" : "유저"}</td>
              <td className="action">
                {(me?.role === "admin" || me?.role === "owner") && <button onClick={() => setShowChangeRole(!showChangeRole)} className="btn btn-small btn-outline text-xs admin-action-btn-eq">변경</button>}
              </td>
            </tr>
            {showChangeRole && (
              <tr>
                <td colSpan={3} style={{ padding: "10px 16px" }}>
                  <div className="flex-row gap-8">
                    <select value={newRole} onChange={e => setNewRole(e.target.value)} className="cw-input">
                      <option value="user">유저</option><option value="moderator">조율자</option><option value="admin">관리자</option><option value="owner">오너</option>
                    </select>
                    <button onClick={() => { act(`/api/admin/users/${u.id}/change-role`, { role: newRole }); setShowChangeRole(false); }} className="btn btn-primary btn-small">저장</button>
                  </div>
                </td>
              </tr>
            )}
            <tr>
              <td className="label">가입일</td>
              <td colSpan={2} className="value">{u.created_at ? new Date(u.created_at).toLocaleString("ko-KR") : "-"}</td>
            </tr>
            <tr>
              <td className="label">최근 활동</td>
              <td colSpan={2} className="value">{u.last_active ? new Date(u.last_active).toLocaleString("ko-KR") : "-"}</td>
            </tr>
            {u.recent_ips.length > 0 && (
              <tr>
                <td className="label">최근 IP</td>
                <td colSpan={2} className="value" style={{ fontFamily: "monospace", fontSize: "0.85em" }}>{u.recent_ips.join(", ")}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Moderation note */}
      <div className="admin-section">
        <label className="admin-section-label">참고사항</label>
        <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={3} className="cw-input w-full resize-vertical" placeholder="관리자 참고용 메모..." onKeyDown={async (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { const form = new FormData(); form.append("note", noteText); const res = await fetch(`/api/admin/users/${u.id}/note`, { method: "POST", credentials: "include", body: form }); if (res.ok) alert("저장됨"); } }} />
        <div className="flex-center" style={{ gap: 8, marginTop: 4 }}>
          <button onClick={async () => {
            const form = new FormData(); form.append("note", noteText);
            const res = await fetch(`/api/admin/users/${u.id}/note`, { method: "POST", credentials: "include", body: form });
            if (res.ok) alert("저장됨");
          }} className="btn btn-primary btn-small">메모 저장</button>
          <div className="admin-spacer" />
          <button onClick={() => setShowModerate(true)} className="btn btn-small btn-moderate">중재</button>
          {u.is_deceased ? (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "undeceased");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">고인 해제</button>
          ) : (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "deceased");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">고인 설정</button>
          )}
          {u.is_frozen && (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "unfreeze");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">동결 해제</button>
          )}
          {u.is_limited && !u.is_suspended && (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "unlimit");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">제한 해제</button>
          )}
          {u.is_sensitive && !u.is_limited && (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "unsensitive");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">민감 해제</button>
          )}
          {u.is_suspended && (
            <button onClick={async () => {
              const form = new FormData(); form.append("action", "unsuspend");
              await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form });
              load();
            }} className="btn btn-small btn-outline">정지 해제</button>
          )}
          <button onClick={() => act(`/api/admin/users/${u.id}/reset-password`)} className="btn btn-small border-default">암호 초기화</button>
          <button onClick={() => router.push(`/@${u.username}`)} className="btn btn-small btn-outline">프로필 보기</button>
        </div>
      </div>

      {/* Moderation log */}
      <div className="admin-detail-card" style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 600, padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>중재 기록 ({logs.length})</div>
        {logs.length === 0 ? (
          <div style={{ padding: "12px 16px", color: "var(--text-muted)", fontSize: "0.85em" }}>기록이 없습니다.</div>
        ) : (
          <div className="admin-table" style={{ display: "block", border: "none" }}>
            <div className="admin-table-header">
              <span style={{ width: 140, flexShrink: 0 }}>시간</span>
              <span style={{ width: 80, flexShrink: 0 }}>진행자</span>
              <span style={{ width: 100, flexShrink: 0 }}>액션</span>
              <span style={{ flex: "1 1 0", minWidth: 0 }}>상세</span>
            </div>
            {logs.map((log: any) => (
              <div key={log.id} className="admin-table-row">
                <span style={{ width: 140, flexShrink: 0, fontSize: "0.85em", fontFamily: "monospace" }}>{log.created_at?.slice(0, 19) || "-"}</span>
                <span style={{ width: 80, flexShrink: 0 }}>{log.username || "-"}</span>
                <span style={{ width: 100, flexShrink: 0 }}>{actionLabels[log.action] || log.action}</span>
                <span style={{ flex: "1 1 0", minWidth: 0, fontSize: "0.85em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{log.details || "-"}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModerate && (
        <div className="reply-modal-backdrop active" onClick={() => setShowModerate(false)}>
          <div className="reply-modal mod-modal" onClick={(e) => e.stopPropagation()}>
            <button className="reply-modal-close" onClick={() => setShowModerate(false)}>×</button>
            <h3>중재</h3>
            <div className="mod-form">
              <div>
                <label className="admin-section-label">조치</label>
                <select value={modAction} onChange={e => setModAction(e.target.value)} className="cw-input mod-select">
                  <option value="warning">경고 — 어떤 동작도 하지 않고 사용자에게 경고를 보냅니다</option>
                  <option value="freeze">동결 — 계정 사용을 막지만 게시물은 유지됩니다</option>
                  <option value="sensitive">민감함 — 모든 미디어를 민감함으로 강제 설정합니다</option>
                  <option value="limit">제한 — 공개 게시물 작성 제한, 팔로우하지 않는 사람에게 숨깁니다</option>
                  <option value="suspend">정지 — 모든 상호작용을 차단하고 모든 내용을 삭제합니다</option>
                </select>
              </div>
              <div>
                <label className="admin-section-label">경고 메세지</label>
                <textarea value={modMessage} onChange={e => setModMessage(e.target.value)} rows={4} className="cw-input mod-textarea" placeholder="사용자에게 보낼 경고 메세지를 입력하세요..." onKeyDown={async (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { const form = new FormData(); form.append("action", modAction); form.append("message", modMessage); if (modEmail) form.append("send_email", "true"); const res = await fetch(`/api/admin/users/${u.id}/moderate`, { method: "POST", credentials: "include", body: form }); if (res.ok) { load(); setShowModerate(false); setMsg("조치가 적용되었습니다."); } else alert("실패"); } }} />
              </div>
              <div>
                <label className="text-sm text-muted flex-center" style={{ gap: 6, cursor: "pointer" }}>
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
