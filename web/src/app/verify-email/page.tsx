"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { refresh } = useAuth();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"verifying" | "success" | "error" | "form">(
    token ? "verifying" : "form"
  );
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (token) {
      (async () => {
        try {
          await api.verifyEmail(token);
          await refresh();
          setStatus("success");
        } catch (err: unknown) {
          setError(err instanceof Error ? err.message : "인증에 실패했습니다.");
          setStatus("error");
        }
      })();
    }
  }, [token, refresh]);

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await api.resendVerification(email);
      setMessage("인증 이메일을 다시 보냈습니다. 이메일을 확인해 주세요.");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "재전송에 실패했습니다.");
    }
    setLoading(false);
  };

  if (status === "verifying") {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p>이메일 인증 중입니다...</p>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <div className="auth-success">
          <p>이메일 인증이 완료되었습니다.</p>
          <p>이제 WRIT의 모든 기능을 이용하실 수 있습니다.</p>
        </div>
        <Link href="/timeline/home" className="btn btn-primary">
          타임라인으로 이동
        </Link>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <h1>WRIT</h1>
      <p>가입 시 등록한 이메일 주소를 입력하면 인증 메일을 다시 보내드립니다.</p>
      <form onSubmit={handleResend}>
        <div className="form-group">
          <label>이메일</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@example.com"
            required
          />
        </div>
        {message && <p className="auth-success">{message}</p>}
        {error && <p className="auth-error">{error}</p>}
        <button type="submit" disabled={loading} className="btn btn-primary">
          {loading ? "..." : "인증 메일 다시 보내기"}
        </button>
      </form>
      <p className="auth-link">
        <Link href="/login">로그인으로 돌아가기</Link>
      </p>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="auth-container"><h1>WRIT</h1><p>로딩 중...</p></div>}>
      <VerifyEmailContent />
    </Suspense>
  );
}
