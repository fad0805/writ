"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import Icon from "@/components/Icon";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [showPwConfirm, setShowPwConfirm] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agreeRules, setAgreeRules] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [isFirstUser, setIsFirstUser] = useState<boolean | null>(null);
  const router = useRouter();
  const { refresh } = useAuth();

  useEffect(() => {
    fetch("/api/v1/instance")
      .then(r => r.json())
      .then(data => {
        const first = (data.stats?.user_count ?? 0) === 0;
        setIsFirstUser(first);
        if (first) setAgreeRules(true);
      })
      .catch(() => setIsFirstUser(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agreeRules) { setError("서버 규칙에 동의해 주세요."); return; }
    if (password !== passwordConfirm) { setError("비밀번호가 일치하지 않습니다."); return; }
    (e.currentTarget.querySelector('button[type="submit"]') as HTMLButtonElement)?.blur();
    setLoading(true); setError("");
    try {
      const form = new FormData();
      form.append("username", username);
      form.append("password", password);
      form.append("email", email);
      if (displayName) form.append("display_name", displayName);
      const res = await fetch("/api/auth/register", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        const data = await res.json();
        if (data.email_sent === false) {
          await refresh();
          router.replace("/users/settings/account");
          return;
        }
        setDone(true);
      } else {
        const d = await res.json();
        setError(d.detail || "가입 실패");
      }
    } catch { setError("가입 실패"); }
    setLoading(false);
  };

  if (done) {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <div className="auth-success">
          <p>가입해 주셔서 감사합니다!</p>
          <p>등록하신 이메일로 인증 링크를 보냈습니다.</p>
          <p>이메일을 확인하여 인증을 완료해 주세요.</p>
        </div>
        <p className="auth-link"><Link href="/verify-email">인증 메일 다시 받기</Link></p>
        <p className="auth-link"><Link href="/login">로그인</Link></p>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <h1>WRIT</h1>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>표시 이름 (선택)</label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="작가명" />
        </div>
        <div className="form-group">
          <label>이메일</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.com" required />
        </div>
        <div className="form-group">
          <label>사용자 이름</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username (소문자)" required />
          <p className="form-help">영문, 숫자, 언더바 사용 가능. 자동으로 소문자 저장됩니다.</p>
        </div>
        <div className="form-group">
          <label>비밀번호</label>
          <div className="pw-input-wrap">
            <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="6자 이상" required />
            <span className="pw-toggle" onClick={() => setShowPw(!showPw)}><Icon name={showPw ? "eye_off" : "eye"} size={16} /></span>
          </div>
        </div>
          <div className="form-group">
            <label>비밀번호 확인</label>
            <div className="pw-input-wrap">
              <input type={showPwConfirm ? "text" : "password"} value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} placeholder="비밀번호 다시 입력" required />
              <span className="pw-toggle" onClick={() => setShowPwConfirm(!showPwConfirm)}><Icon name={showPwConfirm ? "eye_off" : "eye"} size={16} /></span>
            </div>
          {passwordConfirm && password !== passwordConfirm && <p className="form-help" style={{ color: "var(--danger)" }}>비밀번호가 일치하지 않습니다</p>}
        </div>
        {error && <p className="auth-error">{error}</p>}
        {isFirstUser === false && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, fontSize: 14 }}>
            <input type="checkbox" checked={agreeRules} onChange={(e) => setAgreeRules(e.target.checked)} style={{ accentColor: "var(--accent)", width: 16, height: 16, cursor: "pointer" }} />
            <span><a href="/rules" target="_blank" rel="noreferrer" style={{ color: "var(--accent)", textDecoration: "underline" }}>서버 규칙</a>에 동의합니다</span>
          </div>
        )}
        <button type="submit" disabled={loading || (!agreeRules && isFirstUser !== true)} className="btn btn-primary">{loading ? "..." : "가입"}</button>
      </form>
      <p className="auth-link">이미 계정이 있으신가요? <Link href="/login">로그인</Link></p>
    </div>
  );
}
