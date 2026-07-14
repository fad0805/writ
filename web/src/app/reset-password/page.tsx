"use client";
import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import Link from "next/link";
import Icon from "@/components/Icon";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"request" | "reset" | "done">(
    token ? "reset" : "request"
  );
  const [message, setMessage] = useState("");

  const handleRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError(""); setMessage("");
    try {
      await api.forgotPassword(email);
      setMessage("비밀번호 재설정 링크를 이메일로 보냈습니다. 이메일을 확인해 주세요.");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "전송 실패");
    }
    setLoading(false);
  };

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== passwordConfirm) { setError("비밀번호가 일치하지 않습니다."); return; }
    if (password.length < 6) { setError("비밀번호는 6자 이상이어야 합니다."); return; }
    setLoading(true); setError("");
    try {
      await api.resetPassword(token!, password);
      setStep("done");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "리셋 실패");
    }
    setLoading(false);
  };

  if (step === "done") {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <div className="auth-success">
          <p>비밀번호가 재설정되었습니다.</p>
        </div>
        <p className="auth-link"><Link href="/login">로그인</Link></p>
      </div>
    );
  }

  if (step === "request") {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 16, lineHeight: 1.6 }}>
          가입 시 등록한 이메일 주소를 입력하면 비밀번호 재설정 링크를 보내드립니다.
        </p>
        <form onSubmit={handleRequest}>
          <div className="form-group">
            <label>이메일</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.com" required />
          </div>
          {message && <p className="auth-success">{message}</p>}
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" disabled={loading} className="btn btn-primary">{loading ? "..." : "재설정 링크 보내기"}</button>
        </form>
        <p className="auth-link"><Link href="/login">로그인으로 돌아가기</Link></p>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <h1>WRIT</h1>
      <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 16 }}>새 비밀번호를 설정해 주세요.</p>
      <form onSubmit={handleReset}>
        <div className="form-group">
          <label>새 비밀번호</label>
          <div className="pw-input-wrap">
            <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="6자 이상" required />
            <span className="pw-toggle" onClick={() => setShowPw(!showPw)}><Icon name={showPw ? "eye_off" : "eye"} size={16} /></span>
          </div>
        </div>
        <div className="form-group">
          <label>비밀번호 확인</label>
          <div className="pw-input-wrap">
            <input type={showPw ? "text" : "password"} value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} placeholder="비밀번호 다시 입력" required />
          </div>
          {passwordConfirm && password !== passwordConfirm && <p className="form-help" style={{ color: "var(--danger)" }}>비밀번호가 일치하지 않습니다</p>}
        </div>
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary">{loading ? "..." : "비밀번호 재설정"}</button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="auth-container"><h1>WRIT</h1><p>로딩 중...</p></div>}>
      <ResetPasswordContent />
    </Suspense>
  );
}
