"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";
import { api, DeveloperApp, DeveloperToken, User } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type ScopeChild = { scope: string; label: string };
type ScopeGroup = {
  scope: string;
  label: string;
  description: string;
  children?: ScopeChild[];
};

const SCOPE_GROUPS: ScopeGroup[] = [
  {
    scope: "read",
    label: "읽기",
    description: "계정의 모든 데이터 읽기",
    children: [
      { scope: "read:accounts", label: "계정 정보 보기" },
      { scope: "read:blocks", label: "차단 보기" },
      { scope: "read:bookmarks", label: "내 북마크 보기" },
      { scope: "read:collections", label: "컬렉션 보기" },
      { scope: "read:favourites", label: "좋아요 보기" },
      { scope: "read:filters", label: "필터 보기" },
      { scope: "read:follows", label: "팔로우 보기" },
      { scope: "read:lists", label: "리스트 보기" },
      { scope: "read:mutes", label: "뮤트 보기" },
      { scope: "read:notifications", label: "알림 보기" },
      { scope: "read:search", label: "내 권한으로 검색" },
      { scope: "read:statuses", label: "모든 게시물 보기" },
    ],
  },
  {
    scope: "profile",
    label: "프로필",
    description: "내 계정의 프로필 정보만 읽습니다",
  },
  {
    scope: "write",
    label: "쓰기",
    description: "계정 정보 수정",
    children: [
      { scope: "write:accounts", label: "프로필 수정" },
      { scope: "write:blocks", label: "계정 및 도메인 차단" },
      { scope: "write:bookmarks", label: "게시물을 북마크에 넣기" },
      { scope: "write:collections", label: "컬렉션 수정" },
      { scope: "write:conversations", label: "뮤트 및 대화 삭제" },
      { scope: "write:favourites", label: "게시물 좋아요" },
      { scope: "write:filters", label: "필터 만들기" },
      { scope: "write:follows", label: "사람을 팔로우" },
      { scope: "write:lists", label: "리스트 만들기" },
      { scope: "write:media", label: "미디어 파일 업로드" },
      { scope: "write:mutes", label: "사람이나 대화 뮤트" },
      { scope: "write:notifications", label: "알림 모두 지우기" },
      { scope: "write:reports", label: "다른 사람을 신고" },
      { scope: "write:statuses", label: "게시물 게시" },
    ],
  },
  {
    scope: "follow",
    label: "팔로우",
    description: "계정 관계 수정",
  },
  {
    scope: "push",
    label: "푸시",
    description: "푸시 알림 받기",
  },
  {
    scope: "admin:read",
    label: "관리자 읽기",
    description: "서버의 모든 데이터 읽기",
    children: [
      { scope: "admin:read:accounts", label: "모든 계정의 민감한 정보 읽기" },
      { scope: "admin:read:canonical_email_blocks", label: "정규화된 이메일 차단 읽기" },
      { scope: "admin:read:domain_allows", label: "도메인 허용 읽기" },
      { scope: "admin:read:domain_blocks", label: "도메인 차단 읽기" },
      { scope: "admin:read:email_domain_blocks", label: "이메일 도메인 차단 읽기" },
      { scope: "admin:read:ip_blocks", label: "IP 차단 읽기" },
      { scope: "admin:read:reports", label: "신고와 신고된 계정 읽기" },
    ],
  },
  {
    scope: "admin:write",
    label: "관리자 쓰기",
    description: "서버의 모든 데이터 수정",
    children: [
      { scope: "admin:write:accounts", label: "계정에 모더레이션 조치 취하기" },
      { scope: "admin:write:canonical_email_blocks", label: "정규화된 이메일 차단 관리" },
      { scope: "admin:write:domain_allows", label: "도메인 허용 관리" },
      { scope: "admin:write:domain_blocks", label: "도메인 차단 관리" },
      { scope: "admin:write:email_domain_blocks", label: "이메일 도메인 차단 관리" },
      { scope: "admin:write:ip_blocks", label: "IP 차단 관리" },
      { scope: "admin:write:reports", label: "신고 관리" },
    ],
  },
];

const DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob";
const subscribeToNothing = () => () => {};
const getBrowserOrigin = () => window.location.origin;
const getServerOrigin = () => "";

function formatDate(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function canUseAdminScopes(user: User | null) {
  if (!user) return false;
  return !!user.is_admin || ["owner", "admin", "moderator"].includes(user.role || "");
}

function CopyButton({ text, label = "복사" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button type="button" onClick={handleCopy} className="btn btn-small btn-outline" style={{ flexShrink: 0 }}>
      <Icon name="link" size={13} /> {copied ? "복사됨" : label}
    </button>
  );
}

function TokenRow({
  token,
  onRevoke,
}: {
  token: DeveloperToken;
  onRevoke: (tokenId: number) => void;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "10px 12px",
        marginBottom: 8,
        background: "var(--bg-tertiary)",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <code
          style={{
            flex: 1,
            minWidth: 180,
            overflowWrap: "anywhere",
            fontSize: "0.82em",
            color: "var(--text-secondary)",
          }}
        >
          {visible ? token.access_token : "••••••••••••••••••••••••••••••••"}
        </code>
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="btn btn-small btn-outline"
          title={visible ? "토큰 숨기기" : "토큰 보기"}
        >
          <Icon name={visible ? "eye_off" : "eye"} size={14} />
        </button>
        <CopyButton text={token.access_token} />
        <button
          type="button"
          onClick={() => onRevoke(token.id)}
          className="btn btn-small btn-danger"
        >
          <Icon name="trash" size={13} /> 폐기
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
        {token.scopes.map((scope) => (
          <span
            key={scope}
            style={{
              fontSize: "0.75em",
              padding: "1px 6px",
              borderRadius: 10,
              background: "var(--bg-secondary)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            {scope}
          </span>
        ))}
        {token.created_at && (
          <span style={{ fontSize: "0.75em", color: "var(--text-dim)" }}>
            {formatDate(token.created_at)} 발급
          </span>
        )}
      </div>
    </div>
  );
}

function AppCard({
  app,
  busy,
  onCreateToken,
  onDelete,
  onRevokeToken,
}: {
  app: DeveloperApp;
  busy: boolean;
  onCreateToken: (appId: number) => void;
  onDelete: (app: DeveloperApp) => void;
  onRevokeToken: (appId: number, tokenId: number) => void;
}) {
  const oauthUrl = useMemo(() => {
    if (typeof window === "undefined") return "";
    const params = new URLSearchParams({
      client_id: app.client_id,
      redirect_uri: app.redirect_uris[0] || DEFAULT_REDIRECT_URI,
      response_type: "code",
      scope: app.scopes.join(" "),
    });
    return `${window.location.origin}/oauth/authorize?${params.toString()}`;
  }, [app]);

  return (
    <div className="admin-detail-card" style={{ padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.1em" }}>
            {app.name}
            {app.ownerless && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: "0.62em",
                  padding: "2px 7px",
                  borderRadius: 10,
                  background: "var(--bg-tertiary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-muted)",
                  verticalAlign: "middle",
                }}
              >
                기존 API 앱
              </span>
            )}
          </h3>
          <div style={{ fontSize: "0.82em", color: "var(--text-muted)", marginTop: 4 }}>
            {app.created_at ? `${formatDate(app.created_at)} 생성` : "생성일 없음"}
            {app.website && (
              <>
                {" · "}
                <a href={app.website} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
                  {app.website}
                </a>
              </>
            )}
          </div>
        </div>
        <button type="button" onClick={() => onDelete(app)} className="btn btn-small btn-danger">
          <Icon name="trash" size={13} /> 애플리케이션 삭제
        </button>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
        {app.scopes.map((scope) => (
          <span
            key={scope}
            style={{
              fontSize: "0.78em",
              padding: "2px 8px",
              borderRadius: 12,
              background: "var(--bg-tertiary)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            {scope}
          </span>
        ))}
      </div>

      <div className="form-group" style={{ marginTop: 16, marginBottom: 10 }}>
        <label>Client ID</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input readOnly value={app.client_id} className="cw-input" style={{ fontFamily: "monospace", fontSize: "0.82em" }} />
          <CopyButton text={app.client_id} />
        </div>
      </div>
      <div className="form-group" style={{ marginBottom: 10 }}>
        <label>Client Secret</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input readOnly value={app.client_secret} className="cw-input" style={{ fontFamily: "monospace", fontSize: "0.82em" }} />
          <CopyButton text={app.client_secret} />
        </div>
      </div>

      <div className="form-group" style={{ marginBottom: 12 }}>
        <label>리디렉트 URI</label>
        <pre
          style={{
            margin: 0,
            padding: 10,
            borderRadius: 8,
            background: "var(--bg-tertiary)",
            border: "1px solid var(--border)",
            fontSize: "0.82em",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            color: "var(--text-secondary)",
          }}
        >
          {app.redirect_uris.join("\n")}
        </pre>
      </div>

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14, marginTop: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
          <h4 style={{ margin: 0, fontSize: "0.95em" }}>
            <Icon name="lock" size={14} /> 액세스 토큰
          </h4>
          <button
            type="button"
            onClick={() => onCreateToken(app.id)}
            disabled={busy}
            className="btn btn-small btn-primary"
          >
            <Icon name="plus" size={13} /> {busy ? "발급 중..." : "새 토큰 발급"}
          </button>
        </div>
        {app.tokens.length === 0 ? (
          <p className="empty-small" style={{ margin: 0 }}>
            아직 발급된 액세스 토큰이 없습니다.
          </p>
        ) : (
          app.tokens.map((token) => (
            <TokenRow key={token.id} token={token} onRevoke={(tokenId) => onRevokeToken(app.id, tokenId)} />
          ))
        )}
        <p className="form-help" style={{ marginTop: 8 }}>
          이 토큰은 현재 계정의 API 접근에 사용됩니다. 외부에 노출되지 않도록 주의하세요.
        </p>
      </div>

      <div style={{ marginTop: 14 }}>
        <button
          type="button"
          onClick={() => {
            if (oauthUrl) window.open(oauthUrl, "_blank", "noopener,noreferrer");
          }}
          className="btn btn-small btn-outline"
        >
          <Icon name="globe" size={13} /> OAuth 인증 페이지 열기
        </button>
      </div>
    </div>
  );
}

export default function DevelopmentSettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const [apps, setApps] = useState<DeveloperApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const origin = useSyncExternalStore(subscribeToNothing, getBrowserOrigin, getServerOrigin);

  const [showForm, setShowForm] = useState(false);
  const [appName, setAppName] = useState("");
  const [appWebsite, setAppWebsite] = useState("");
  const [redirectUrisText, setRedirectUrisText] = useState(DEFAULT_REDIRECT_URI);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["read"]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [busyAppId, setBusyAppId] = useState<number | null>(null);

  const adminAllowed = canUseAdminScopes(user);
  const visibleGroups = useMemo(
    () => SCOPE_GROUPS.filter((group) => adminAllowed || !group.scope.startsWith("admin:")),
    [adminAllowed],
  );

  const loadApps = useCallback(async () => {
    try {
      const data = await api.getDeveloperApps();
      setApps(data.apps);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "애플리케이션을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading || !user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadApps();
  }, [authLoading, user, loadApps]);

  const toggleParentScope = (group: ScopeGroup) => {
    setSelectedScopes((prev) => {
      const childScopes = group.children?.map((child) => child.scope) || [];
      if (prev.includes(group.scope)) {
        return prev.filter((scope) => scope !== group.scope && !childScopes.includes(scope));
      }
      return [...prev.filter((scope) => !childScopes.includes(scope)), group.scope];
    });
  };

  const toggleChildScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((item) => item !== scope) : [...prev, scope],
    );
  };

  const resetForm = () => {
    setAppName("");
    setAppWebsite("");
    setRedirectUrisText(DEFAULT_REDIRECT_URI);
    setSelectedScopes(["read"]);
    setCreateError("");
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setCreateError("");
    setNotice("");

    const redirectUris = redirectUrisText
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);

    if (!appName.trim()) {
      setCreateError("애플리케이션 이름을 입력해 주세요.");
      return;
    }
    if (redirectUris.length === 0) {
      setCreateError("리디렉트 URI를 하나 이상 입력해 주세요.");
      return;
    }
    if (selectedScopes.length === 0) {
      setCreateError("범위를 하나 이상 선택해 주세요.");
      return;
    }

    setCreating(true);
    try {
      const result = await api.createDeveloperApp({
        client_name: appName.trim(),
        website: appWebsite.trim() || undefined,
        redirect_uris: redirectUris,
        scopes: selectedScopes,
      });
      setApps((prev) => [result.app, ...prev]);
      setShowForm(false);
      resetForm();
      setNotice("애플리케이션이 생성되었습니다.");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "애플리케이션 생성에 실패했습니다.");
    } finally {
      setCreating(false);
    }
  };

  const handleCreateToken = async (appId: number) => {
    setBusyAppId(appId);
    setNotice("");
    setError("");
    try {
      const result = await api.createDeveloperToken(appId);
      setApps((prev) =>
        prev.map((app) =>
          app.id === appId ? { ...app, tokens: [result.token, ...app.tokens] } : app,
        ),
      );
      setNotice("액세스 토큰이 발급되었습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "토큰 발급에 실패했습니다.");
    } finally {
      setBusyAppId(null);
    }
  };

  const handleDeleteApp = async (app: DeveloperApp) => {
    if (!window.confirm(`"${app.name}" 애플리케이션을 삭제할까요?\n발급된 모든 토큰도 함께 폐기됩니다.`)) {
      return;
    }
    setError("");
    setNotice("");
    try {
      await api.deleteDeveloperApp(app.id);
      setApps((prev) => prev.filter((item) => item.id !== app.id));
      setNotice("애플리케이션을 삭제했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "애플리케이션 삭제에 실패했습니다.");
    }
  };

  const handleRevokeToken = async (appId: number, tokenId: number) => {
    if (!window.confirm("이 액세스 토큰을 폐기할까요? 이 토큰을 사용하는 앱은 더 이상 접근할 수 없습니다.")) {
      return;
    }
    setError("");
    setNotice("");
    try {
      await api.revokeDeveloperToken(tokenId);
      setApps((prev) =>
        prev.map((app) =>
          app.id === appId
            ? { ...app, tokens: app.tokens.filter((token) => token.id !== tokenId) }
            : app,
        ),
      );
      setNotice("액세스 토큰을 폐기했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "토큰 폐기에 실패했습니다.");
    }
  };

  if (authLoading || (user && loading)) {
    return (
      <>
        <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
        <SettingsNav current="development" />
        <p className="empty-state">로딩 중...</p>
      </>
    );
  }

  if (!user) {
    return (
      <>
        <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
        <SettingsNav current="development" />
        <p className="empty-state">로그인이 필요합니다.</p>
      </>
    );
  }

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
      <SettingsNav current="development" />

      <div className="novel-form" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.05em" }}><Icon name="link" size={15} /> 애플리케이션</h3>
            <p className="form-help" style={{ marginTop: 4 }}>
              OAuth 앱을 등록하고 API 액세스 토큰을 발급할 수 있습니다.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setShowForm((value) => !value);
              setCreateError("");
            }}
            className={`btn btn-small ${showForm ? "btn-outline" : "btn-primary"}`}
          >
            <Icon name={showForm ? "x" : "plus"} size={13} /> {showForm ? "취소" : "새 애플리케이션"}
          </button>
        </div>

        {showForm && (
          <form onSubmit={handleCreate} style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 18 }}>
            <div className="form-group">
              <label>애플리케이션 이름 *</label>
              <input
                type="text"
                value={appName}
                onChange={(event) => setAppName(event.target.value)}
                placeholder="예: 내 Mastodon 클라이언트"
                className="cw-input"
                maxLength={256}
                required
              />
            </div>
            <div className="form-group">
              <label>애플리케이션 웹사이트</label>
              <input
                type="url"
                value={appWebsite}
                onChange={(event) => setAppWebsite(event.target.value)}
                placeholder="https://example.com"
                className="cw-input"
              />
            </div>
            <div className="form-group">
              <label>리디렉트 URI *</label>
              <textarea
                value={redirectUrisText}
                onChange={(event) => setRedirectUrisText(event.target.value)}
                rows={4}
                className="cw-input"
                style={{ resize: "vertical", fontFamily: "monospace", fontSize: "0.88em" }}
                required
              />
              <p className="form-help">
                한 줄에 하나의 URI를 작성하세요. 로컬 테스트에는 {DEFAULT_REDIRECT_URI}를 사용할 수 있습니다.
              </p>
            </div>

            <div className="form-group">
              <label>범위 *</label>
              <p className="form-help" style={{ marginTop: 0, marginBottom: 10 }}>
                애플리케이션에 허용할 API입니다. 최상위 스코프를 선택하면 개별 항목은 자동으로 포함됩니다.
              </p>
              {visibleGroups.map((group) => {
                const parentSelected = selectedScopes.includes(group.scope);
                return (
                  <div
                    key={group.scope}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      padding: "10px 12px",
                      marginBottom: 8,
                      background: "var(--bg-tertiary)",
                    }}
                  >
                    <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2, color: "var(--text-primary)" }}>
                      <input
                        type="checkbox"
                        checked={parentSelected}
                        onChange={() => toggleParentScope(group)}
                      />
                      <span style={{ fontWeight: 600 }}>{group.label}</span>
                      <code style={{ fontSize: "0.78em", color: "var(--text-muted)" }}>{group.scope}</code>
                    </label>
                    <p className="form-help" style={{ marginTop: 0, marginBottom: group.children ? 8 : 0 }}>
                      {group.description}
                    </p>
                    {group.children && (
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
                          gap: 4,
                          paddingLeft: 24,
                        }}
                      >
                        {group.children.map((child) => {
                          const childSelected = parentSelected || selectedScopes.includes(child.scope);
                          return (
                            <label
                              key={child.scope}
                              style={{
                                display: "flex",
                                alignItems: "flex-start",
                                gap: 6,
                                fontSize: "0.84em",
                                color: parentSelected ? "var(--text-muted)" : "var(--text-secondary)",
                                cursor: parentSelected ? "default" : "pointer",
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={childSelected}
                                disabled={parentSelected}
                                onChange={() => toggleChildScope(child.scope)}
                                style={{ marginTop: 2 }}
                              />
                              <span>
                                {child.label}
                                <br />
                                <code style={{ fontSize: "0.88em", color: "var(--text-dim)" }}>{child.scope}</code>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {createError && <p className="auth-error">{createError}</p>}
            <div className="form-actions">
              <button type="button" onClick={() => { setShowForm(false); resetForm(); }} className="btn btn-outline">
                취소
              </button>
              <button type="submit" disabled={creating} className="btn btn-primary">
                {creating ? "생성 중..." : "애플리케이션 생성"}
              </button>
            </div>
          </form>
        )}
      </div>

      {notice && <p className="auth-success" style={{ marginBottom: 12 }}>{notice}</p>}
      {error && <p className="auth-error" style={{ marginBottom: 12 }}>{error}</p>}

      {apps.length === 0 ? (
        <div className="novel-form">
          <p className="empty-small" style={{ margin: 0 }}>
            아직 등록된 애플리케이션이 없습니다. 새 애플리케이션을 만들어 API를 사용해 보세요.
          </p>
        </div>
      ) : (
        apps.map((app) => (
          <AppCard
            key={app.id}
            app={app}
            busy={busyAppId === app.id}
            onCreateToken={handleCreateToken}
            onDelete={handleDeleteApp}
            onRevokeToken={handleRevokeToken}
          />
        ))
      )}

      <div className="novel-form" style={{ marginTop: 20 }}>
        <h3 style={{ marginTop: 0, fontSize: "1.05em" }}><Icon name="globe" size={15} /> API 사용</h3>
        <p style={{ fontSize: "0.9em", color: "var(--text-secondary)" }}>
          발급한 액세스 토큰을 <code>Authorization: Bearer</code> 헤더에 넣으면 Mastodon 호환 API를 사용할 수 있습니다.
        </p>
        <div className="form-group">
          <label>API 기본 URL</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input readOnly value={origin ? `${origin}/api` : "https://your-instance/api"} className="cw-input" style={{ fontFamily: "monospace", fontSize: "0.82em" }} />
            <CopyButton text={origin ? `${origin}/api` : ""} />
          </div>
        </div>
        <div className="form-group">
          <label>토큰 확인 예시</label>
          <pre
            style={{
              margin: 0,
              padding: 12,
              borderRadius: 8,
              background: "var(--bg-tertiary)",
              border: "1px solid var(--border)",
              fontSize: "0.82em",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              color: "var(--text-secondary)",
            }}
          >
{`curl -H "Authorization: Bearer <ACCESS_TOKEN>" \\
  ${origin || "https://your-instance"}/api/v1/accounts/verify_credentials`}
          </pre>
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>OAuth 토큰 발급</label>
          <pre
            style={{
              margin: 0,
              padding: 12,
              borderRadius: 8,
              background: "var(--bg-tertiary)",
              border: "1px solid var(--border)",
              fontSize: "0.82em",
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
              color: "var(--text-secondary)",
            }}
          >
{`POST ${origin || "https://your-instance"}/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<AUTHORIZATION_CODE>
&client_id=<CLIENT_ID>
&client_secret=<CLIENT_SECRET>
&redirect_uri=<REDIRECT_URI>`}
          </pre>
        </div>
      </div>
    </>
  );
}
