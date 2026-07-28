"use client";
import { Suspense, useState, useEffect } from "react";
import { api, storeAccount, setActiveAccountId } from "@/lib/api";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";
import Icon from "@/components/Icon";

function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const isAddMode = searchParams.get("add") === "1";
  const { user, loading: authLoading, refresh } = useAuth();

  useEffect(() => {
    if (!authLoading && user && !isAddMode) router.replace("/timeline/home");
  }, [user, authLoading, router, isAddMode]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (user && !isAddMode) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const result = await api.login(username, password);
      if (result.user && result.session_token) {
        storeAccount({
          user_id: result.user.id,
          username: result.user.username,
          display_name: result.user.display_name,
          avatar: result.user.avatar || "",
          session_token: result.session_token,
        });
        setActiveAccountId(result.user.id);
      }
      await refresh();
      router.push("/timeline/home");
    } catch (err: unknown) { setError(err instanceof Error ? err.message : String(err)); }
    setLoading(false);
  };

  return (
    <div className="auth-container">
      <h1>WRIT</h1>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>사용자 이름 또는 이메일</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username 또는 email@example.com" required />
        </div>
        <div className="form-group">
          <label>비밀번호</label>
          <div className="pw-input-wrap">
            <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" required />
            <span className="pw-toggle" onClick={() => setShowPw(!showPw)}><Icon name={showPw ? "eye_off" : "eye"} size={16} /></span>
          </div>
        </div>
        {error && (
          <p className="auth-error">
            {error}
            {error.includes("이메일 인증") && (
              <span style={{ display: "block", marginTop: 8 }}>
                <Link href="/verify-email">인증 메일 다시 보내기</Link>
              </span>
            )}
          </p>
        )}
        <button type="submit" disabled={loading} className="btn btn-primary">{loading ? "..." : "로그인"}</button>
      </form>
      <p className="auth-link"><Link href="/reset-password">비밀번호를 잊으셨나요?</Link></p>
      <p className="auth-link">계정이 없으신가요? <Link href="/register">가입하기</Link></p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="empty-state">로딩 중...</div>}>
      <LoginForm />
    </Suspense>
  );
}
