"use client";
import { useState } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function AccountSettingsPage() {
  const [email, setEmail] = useState("");
  const [emailMsg, setEmailMsg] = useState("");
  const [emailErr, setEmailErr] = useState("");
  const [emailLoading, setEmailLoading] = useState(false);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [pwErr, setPwErr] = useState("");
  const [pwLoading, setPwLoading] = useState(false);

  const handleChangeEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailLoading(true); setEmailMsg(""); setEmailErr("");
    try {
      const form = new FormData();
      form.append("email", email);
      const res = await fetch("/api/settings/change-email", { method: "POST", credentials: "include", body: form });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { setEmailErr(d.detail || "실패"); }
      else { setEmailMsg("변경된 이메일로 인증 메일을 보냈습니다."); setEmail(""); }
    } catch { setEmailErr("실패"); }
    setEmailLoading(false);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwLoading(true); setPwMsg(""); setPwErr("");
    try {
      const form = new FormData();
      form.append("current_password", curPw);
      form.append("new_password", newPw);
      const res = await fetch("/api/settings/change-password", { method: "POST", credentials: "include", body: form });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { setPwErr(d.detail || "실패"); }
      else { setPwMsg("비밀번호가 변경되었습니다."); setCurPw(""); setNewPw(""); }
    } catch { setPwErr("실패"); }
    setPwLoading(false);
  };

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 설정 관리</h2>
      </div>
      <SettingsNav current="account" />

      <form onSubmit={handleChangeEmail} className="novel-form" style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: "1.1em", marginBottom: 16 }}><Icon name="mail" /> 이메일 변경</h3>
        <div className="form-group">
          <label>새 이메일 주소</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="new@example.com" className="cw-input" required />
          <p className="form-help">변경 후 새 이메일로 인증 메일이 발송됩니다. 인증을 완료해야 계정을 사용할 수 있습니다.</p>
        </div>
        {emailMsg && <p className="auth-success">{emailMsg}</p>}
        {emailErr && <p className="auth-error">{emailErr}</p>}
        <div className="form-actions">
          <button type="submit" disabled={emailLoading} className="btn btn-primary">
            {emailLoading ? "..." : "이메일 변경"}
          </button>
        </div>
      </form>

      <form onSubmit={handleChangePassword} className="novel-form">
        <h3 style={{ fontSize: "1.1em", marginBottom: 16 }}><Icon name="lock" /> 비밀번호 변경</h3>
        <div className="form-group">
          <label>현재 비밀번호</label>
          <input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} placeholder="현재 비밀번호" className="cw-input" required />
        </div>
        <div className="form-group">
          <label>새 비밀번호</label>
          <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="6자 이상" className="cw-input" required />
          <p className="form-help">최소 6자 이상 입력해 주세요.</p>
        </div>
        {pwMsg && <p className="auth-success">{pwMsg}</p>}
        {pwErr && <p className="auth-error">{pwErr}</p>}
        <div className="form-actions">
          <button type="submit" disabled={pwLoading} className="btn btn-primary">
            {pwLoading ? "..." : "비밀번호 변경"}
          </button>
        </div>
      </form>
    </>
  );
}
