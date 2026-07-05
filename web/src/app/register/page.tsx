"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { refresh } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.register(username, password, displayName || undefined);
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
          <label>표시 이름 (선택)</label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="작가명" />
        </div>
        <div className="form-group">
          <label>사용자 이름</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" required />
        </div>
        <div className="form-group">
          <label>비밀번호</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="6자 이상" required />
        </div>
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary">{loading ? "..." : "가입"}</button>
      </form>
      <p className="auth-link">이미 계정이 있으신가요? <Link href="/login">로그인</Link></p>
    </div>
  );
}
