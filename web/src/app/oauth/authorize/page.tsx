"use client";
import { useState, useEffect } from "react";

function OAuthAuthorizeForm() {
  const [clientId, setClientId] = useState("");
  const [redirectUri, setRedirectUri] = useState("urn:ietf:wg:oauth:2.0:oob");
  const [responseType, setResponseType] = useState("code");
  const [scope, setScope] = useState("read write push");
  const [state, setState] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [authCode, setAuthCode] = useState("");
  const [deepLink, setDeepLink] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    setClientId(sp.get("client_id") || "");
    setRedirectUri(sp.get("redirect_uri") || "urn:ietf:wg:oauth:2.0:oob");
    setResponseType(sp.get("response_type") || "code");
    setScope(sp.get("scope") || "read write push");
    setState(sp.get("state") || "");
    setReady(true);
  }, []);

  if (!ready) return <div className="empty-state">로딩 중...</div>;

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    console.log("[oauth] handleSubmit called", { username, clientId, redirectUri });
    try {
      const res = await fetch("/api/oauth/authorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
      console.log("[oauth] fetch returned", res.status);
      const data = await res.json();
      console.log("[oauth] data", data);

      if (data.error) {
        setError(data.error);
        setLoading(false);
        return;
      }

      if (data.redirect) {
        const isHttp = data.redirect.startsWith("http://") || data.redirect.startsWith("https://");
        if (isHttp) {
          window.location.href = data.redirect;
          return;
        }
        setDeepLink(data.redirect);
        setLoading(false);
        return;
      }

      if (data.code) {
        if (redirectUri === "urn:ietf:wg:oauth:2.0:oob") {
          setAuthCode(data.code);
          setLoading(false);
          return;
        }
        const sep = redirectUri.includes("?") ? "&" : "?";
        const deepLinkUrl = `${redirectUri}${sep}code=${data.code}${state ? `&state=${encodeURIComponent(state)}` : ""}`;
        setDeepLink(deepLinkUrl);
        setLoading(false);
        return;
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setLoading(false);
  };

  if (deepLink) {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p style={{ marginBottom: 12, textAlign: "center" }}>앱으로 돌아가려면 아래 버튼을 누르세요:</p>
        <a href={deepLink} className="btn btn-primary" style={{ display: "block", textAlign: "center", textDecoration: "none" }}>
          앱에서 열기
        </a>
        <p style={{ marginTop: 16, fontSize: 12, color: "var(--text-secondary, #666)", textAlign: "center", wordBreak: "break-all" }}>
          버튼이 안 눌리면: <code style={{ userSelect: "all" }}>{deepLink}</code>
        </p>
      </div>
    );
  }

  if (authCode) {
    return (
      <div className="auth-container">
        <h1>WRIT</h1>
        <p style={{ marginBottom: 8, textAlign: "center" }}>인증 코드:</p>
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
        <p style={{ marginTop: 12, fontSize: 14, color: "var(--text-secondary, #888)", textAlign: "center" }}>
          이 코드를 앱에 입력하세요.
        </p>
      </div>
    );
  }

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
              {showPw ? "숨기기" : "보기"}
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
  return <OAuthAuthorizeForm />;
}
