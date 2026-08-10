"use client";
import { useState, useEffect } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function AccountSettingsPage() {
  const { user, refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPwConfirm, setNewPwConfirm] = useState("");
  const [showCurPw, setShowCurPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [showNewPwConfirm, setShowNewPwConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [mailSent, setMailSent] = useState(false);

  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deletePw, setDeletePw] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleteErr, setDeleteErr] = useState("");
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [sessions, setSessions] = useState<{ id: number; device_name: string; ip_address: string; is_current: boolean; last_active: string; created_at: string }[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);

  useEffect(() => {
    fetch("/api/sessions", { credentials: "include" })
      .then(r => r.json()).then(d => { setSessions(d.sessions || []); setSessionsLoading(false); })
      .catch(() => setSessionsLoading(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setMsg(""); setErr(""); setMailSent(false);
    try {
      if (email) {
        const form = new FormData();
        form.append("email", email);
        form.append("password", curPw || "");
        const res = await fetch("/api/settings/change-email", { method: "POST", credentials: "include", body: form });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) { setErr(d.detail || "이메일 변경 실패"); setLoading(false); return; }
        setMsg("이메일이 변경되었습니다. 인증 메일을 확인해 주세요.");
        setEmail("");
      }
      if (curPw && newPw) {
        if (newPw !== newPwConfirm) { setErr("새 비밀번호가 일치하지 않습니다."); setLoading(false); return; }
        const form = new FormData();
        form.append("current_password", curPw);
        form.append("new_password", newPw);
        const res = await fetch("/api/settings/change-password", { method: "POST", credentials: "include", body: form });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) { setErr(d.detail || "비밀번호 변경 실패"); setLoading(false); return; }
        setCurPw(""); setNewPw(""); setNewPwConfirm("");
      }
      setMsg("저장되었습니다.");
      await refresh();
    } catch { setErr("오류 발생"); }
    setLoading(false);
  };

  const sendVerification = async () => {
    setErr(""); setMailSent(false);
    try {
      const res = await fetch("/api/settings/send-verification-email", { method: "POST", credentials: "include" });
      const d = await res.json().catch(() => ({}));
      if (d.already_verified) { await refresh(); return; }
      if (res.ok) setMailSent(true);
      else setErr(d.detail || "메일 전송 실패");
    } catch { setErr("메일 전송 실패"); }
  };

  const handleDeleteAccount = async () => {
    setDeleteErr(""); setDeleteLoading(true);
    try {
      const form = new FormData();
      form.append("password", deletePw);
      form.append("confirm", deleteConfirm);
      const res = await fetch("/api/settings/delete-account", { method: "POST", credentials: "include", body: form });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { setDeleteErr(d.detail || "회원 탈퇴 실패"); setDeleteLoading(false); return; }
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
      router.push("/");
    } catch { setDeleteErr("오류가 발생했습니다."); setDeleteLoading(false); }
  };

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 설정 관리</h2>
      </div>
      <SettingsNav current="account" />

      <div className="admin-detail-card" style={{ padding: 20 }}>
        <form onSubmit={handleSubmit}>
          <div className="form-group" style={{ marginBottom: 24 }}>
            <label>새 이메일 주소</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={user?.email || ""} className="cw-input" />
            <p className="form-help">변경할 이메일 주소를 입력하세요. 비워두면 변경되지 않습니다.</p>
          </div>
          <div className="form-group" style={{ marginBottom: 8 }}>
            <label>이메일 인증 상태</label>
            {user?.email_verified ? (
              <p style={{ fontSize: 13, color: "var(--success)", margin: 0 }}>✓ 이메일 인증됨</p>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, color: "var(--danger)" }}>이메일 미인증</span>
                <button type="button" onClick={sendVerification} className="btn btn-small btn-outline text-xs" style={{ fontSize: 12, padding: "2px 8px" }}>인증 메일 보내기</button>
                {mailSent && <span style={{ fontSize: 13, color: "var(--success)" }}>인증 메일을 보냈습니다. 확인해 주세요.</span>}
              </div>
            )}
          </div>
          <div className="form-group" style={{ marginBottom: 8 }}>
            <label>현재 비밀번호</label>
            <div className="pw-input-wrap">
              <input type={showCurPw ? "text" : "password"} value={curPw} onChange={(e) => setCurPw(e.target.value)} placeholder="현재 비밀번호" className="cw-input" />
              <span className="pw-toggle" onClick={() => setShowCurPw(!showCurPw)}><Icon name={showCurPw ? "eye_off" : "eye"} size={16} /></span>
            </div>
          </div>
          <div className="form-group">
            <label>새 비밀번호</label>
            <div className="pw-input-wrap">
              <input type={showNewPw ? "text" : "password"} value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="6자 이상" className="cw-input" />
              <span className="pw-toggle" onClick={() => setShowNewPw(!showNewPw)}><Icon name={showNewPw ? "eye_off" : "eye"} size={16} /></span>
            </div>
          </div>
          <div className="form-group">
            <label>새 비밀번호 확인</label>
            <div className="pw-input-wrap">
              <input type={showNewPwConfirm ? "text" : "password"} value={newPwConfirm} onChange={(e) => setNewPwConfirm(e.target.value)} placeholder="새 비밀번호 다시 입력" className="cw-input" />
              <span className="pw-toggle" onClick={() => setShowNewPwConfirm(!showNewPwConfirm)}><Icon name={showNewPwConfirm ? "eye_off" : "eye"} size={16} /></span>
            </div>
            {newPwConfirm && newPw !== newPwConfirm && <p className="form-help" style={{ color: "var(--danger)" }}>비밀번호가 일치하지 않습니다</p>}
          </div>
          <div className="form-group">
            <p className="form-help">비워두면 비밀번호가 변경되지 않습니다. 변경 시 현재 비밀번호와 새 비밀번호를 모두 입력하세요.</p>
          </div>
          {msg && <p className="auth-success">{msg}</p>}
          {err && <p className="auth-error">{err}</p>}
          <div className="form-actions">
            <button type="submit" disabled={loading} className="btn btn-primary">
              {loading ? "저장 중..." : "저장"}
            </button>
          </div>
        </form>
      </div>

      <div className="admin-detail-card" style={{ padding: 20, marginTop: 16 }}>
        <h3 style={{ fontSize: 16, marginTop: 0, marginBottom: 12 }}><Icon name="bell" /> 로그인 기기</h3>
        {sessionsLoading ? (
          <p className="empty-small">로딩 중...</p>
        ) : sessions.length === 0 ? (
          <p className="empty-small">등록된 기기가 없습니다.</p>
        ) : sessions.sort((a, b) => (a.is_current ? 0 : 1) - (b.is_current ? 0 : 1)).map(dev => (
          <div key={dev.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: dev.is_current ? "var(--card-hover)" : "var(--bg-tertiary)", borderRadius: 8, marginBottom: 6, border: dev.is_current ? "1px solid var(--accent)" : "1px solid var(--border)" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: "0.9em" }}>{dev.device_name}</div>
              <div style={{ fontSize: "0.8em", color: "var(--text-muted)" }}>
                {dev.ip_address && <span>{dev.ip_address}</span>}
                {dev.last_active && <span> · 최근 접속 {new Date(dev.last_active).toLocaleString()}</span>}
              </div>
            </div>
            {dev.is_current ? (
              <span style={{ color: "var(--accent)", fontSize: "0.85em", fontWeight: 600, whiteSpace: "nowrap" }}>현재 사용 중</span>
            ) : (
              <button type="button" onClick={async () => {
                if (!confirm("이 기기의 로그인을 해제하시겠습니까?")) return;
                try {
                  const res = await fetch(`/api/sessions/${dev.id}/delete`, { method: "POST", credentials: "include" });
                  if (res.ok) setSessions(prev => prev.filter(d => d.id !== dev.id));
                  else { const data = await res.json(); alert(data.detail || "해제 실패"); }
                } catch {}
              }} style={{ background: "none", border: "none", color: "var(--danger)", cursor: "pointer", fontSize: "0.85em", whiteSpace: "nowrap" }}>해제</button>
            )}
          </div>
        ))}
      </div>

      <div className="admin-detail-card" style={{ padding: 20, marginTop: 16, borderColor: "var(--danger)" }}>
        <h3 style={{ fontSize: 16, color: "var(--danger)", marginTop: 0 }}>회원 탈퇴</h3>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
          계정을 탈퇴하면 프로필, 게시글, 팔로우 관계 등 모든 데이터가 삭제되며 복구할 수 없습니다.
        </p>
        <button type="button" onClick={() => { setShowDeleteModal(true); setDeletePw(""); setDeleteConfirm(""); setDeleteErr(""); }} className="btn btn-danger">
          회원 탈퇴
        </button>
      </div>

      {showDeleteModal && (
        <div className="modal-overlay" onClick={() => !deleteLoading && setShowDeleteModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420, padding: 20 }}>
            <h3 style={{ marginTop: 0, color: "var(--danger)" }}>회원 탈퇴</h3>
            <p style={{ fontSize: 13, marginBottom: 16 }}>
              되돌릴 수 없습니다. 탈퇴하려면 비밀번호와 아이디를 확인하세요.
            </p>
            <div className="form-group" style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 13 }}>비밀번호</label>
              <input
                type="password"
                value={deletePw}
                onChange={(e) => setDeletePw(e.target.value)}
                placeholder="현재 비밀번호"
                className="cw-input"
                disabled={deleteLoading}
              />
            </div>
            <div className="form-group" style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 13 }}>아이디 확인 (<code>{user?.username}</code> 입력)</label>
              <input
                type="text"
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                placeholder={user?.username || ""}
                className="cw-input"
                disabled={deleteLoading}
              />
            </div>
            {deleteErr && <p className="auth-error" style={{ marginBottom: 12 }}>{deleteErr}</p>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" onClick={() => setShowDeleteModal(false)} className="btn btn-outline" disabled={deleteLoading}>취소</button>
              <button
                type="button"
                onClick={handleDeleteAccount}
                className="btn btn-danger"
                disabled={deleteLoading || !deletePw || !deleteConfirm}
              >
                {deleteLoading ? "탈퇴 중..." : "탈퇴하기"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
