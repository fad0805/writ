"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { refresh } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.login(username, password);
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
          <label>사용자 이름</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" required />
        </div>
        <div className="form-group">
          <label>비밀번호</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" required />
        </div>
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary">{loading ? "..." : "로그인"}</button>
      </form>
      <p className="auth-link">계정이 없으신가요? <Link href="/register">가입하기</Link></p>
    </div>
  );
}
