"use client";
import { useState } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function AccountSettingsPage() {
  const [email, setEmail] = useState("");
  const [verifyNow, setVerifyNow] = useState(false);
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPwConfirm, setNewPwConfirm] = useState("");
  const [showCurPw, setShowCurPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [showNewPwConfirm, setShowNewPwConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setMsg(""); setErr("");
    try {
      if (email) {
        const form = new FormData();
        form.append("email", email);
        form.append("password", curPw || "");
        form.append("verify_now", verifyNow ? "true" : "false");
        const res = await fetch("/api/settings/change-email", { method: "POST", credentials: "include", body: form });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) { setErr(d.detail || "이메일 변경 실패"); setLoading(false); return; }
        if (d.verified) setMsg("이메일이 변경되었고 인증되었습니다.");
        else setMsg("이메일이 변경되었습니다. 인증 메일을 확인해 주세요.");
        setEmail(""); setVerifyNow(false);
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
    } catch { setErr("오류 발생"); }
    setLoading(false);
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
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="new@example.com" className="cw-input" />
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, fontSize: 13 }}>
              <input type="checkbox" checked={verifyNow} onChange={(e) => setVerifyNow(e.target.checked)} style={{ accentColor: "var(--accent)", width: 15, height: 15, cursor: "pointer" }} />
              <span>지금 인증 (인증 메일 없이 바로 변경)</span>
            </div>
            <p className="form-help">변경할 이메일 주소를 입력하세요. 비워두면 변경되지 않습니다.</p>
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
    </>
  );
}
