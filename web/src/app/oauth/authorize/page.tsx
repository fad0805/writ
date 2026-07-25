"use client";
import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import Icon from "@/components/Icon";

function OAuthAuthorizeForm() {
  const searchParams = useSearchParams();

  const clientId = searchParams.get("client_id") || "";
  const redirectUri = searchParams.get("redirect_uri") || "urn:ietf:wg:oauth:2.0:oob";
  const responseType = searchParams.get("response_type") || "code";
  const scope = searchParams.get("scope") || "read write push";
  const state = searchParams.get("state") || "";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [authCode, setAuthCode] = useState("");

  if (responseType !== "code") {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p className="auth-error">지원하지 않는 response_type입니다.</p>
      </div>
    );
  }

  if (!clientId) {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p className="auth-error">client_id가 없습니다.</p>
      </div>
    );
  }

  if (authCode) {
    if (redirectUri === "urn:ietf:wg:oauth:2.0:oob") {
      return (
        <div className="auth-container">
          <h1>WRIT</h1>
          <p style={{ marginBottom: 8 }}>인증 코드:</p>
          <div style={{
            background: "var(--bg-elevated, #1a1a2e)",
            border: "1px solid var(--border, #333)",
            borderRadius: 8,
            padding: 16,
            fontFamily: "monospace",
            fontSize: 18,
            wordBreak: "break-all",
            userSelect: "all",
            textAlign: "center",
          }}>
            {authCode}
          </div>
          <p style={{ marginTop: 12, fontSize: 14, color: "var(--text-secondary, #888)" }}>
            이 코드를 앱에 입력하세요.
          </p>
        </div>
      );
    }
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/oauth/authorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          username,
          password,
          client_id: clientId,
          redirect_uri: redirectUri,
          response_type: responseType,
          scope,
          state,
        }),
      });
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        setLoading(false);
        return;
      }

      if (data.code) {
        if (redirectUri === "urn:ietf:wg:oauth:2.0:oob") {
          setAuthCode(data.code);
          setLoading(false);
          return;
        }
        window.location.href = data.redirect;
        return;
      }

      if (data.redirect) {
        window.location.href = data.redirect;
        return;
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setLoading(false);
  };

  return (
    <div className="auth-container">
      <h1>WRIT</h1>
      <p style={{ color: "var(--text-secondary, #888)", marginBottom: 24, fontSize: 14, textAlign: "center" }}>
        앱이 계정에 접근을 요청합니다
      </p>
      {error && <p className="auth-error">{error}</p>}
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label>사용자 이름 또는 이메일</label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="username 또는 email@example.com"
            autoComplete="username"
            required
          />
        </div>
        <div className="form-group">
          <label>비밀번호</label>
          <div className="pw-input-wrap">
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="password"
              autoComplete="current-password"
              required
            />
            <span className="pw-toggle" onClick={() => setShowPw(!showPw)}>
              <Icon name={showPw ? "eye_off" : "eye"} size={16} />
            </span>
          </div>
        </div>
        <p style={{ fontSize: 12, color: "var(--text-secondary, #666)", marginBottom: 16, textAlign: "center" }}>
          허용 범위: {scope}
        </p>
        <button type="submit" disabled={loading} className="btn btn-primary">
          {loading ? "..." : "로그인 및 허용"}
        </button>
      </form>
    </div>
  );
}

export default function OAuthAuthorizePage() {
  return (
    <Suspense fallback={<div className="empty-state">로딩 중...</div>}>
      <OAuthAuthorizeForm />
    </Suspense>
  );
}
