"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { isStaff, can, PERMS } from "@/lib/permissions";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";
import Link from "next/link";

interface RemoteUser {
  id: number;
  username: string;
  display_name: string;
  profile_image: string | null;
  remote_url: string;
}

interface ServerDetail {
  domain: string;
  total_users: number;
  local_following: number;
  local_followers: number;
  is_reachable: boolean;
  is_blocked: boolean;
  is_muted: boolean;
  is_media_muted: boolean;
  users: RemoteUser[];
  has_more: boolean;
  total_users_count: number;
  server_icon: string;
}

interface ModLog {
  id: number;
  created_at?: string;
  username?: string;
  action: string;
  details?: string;
}

const actionLabels: Record<string, string> = {
  federation_block: "연합 차단", federation_unblock: "연합 차단 해제",
  server_mute: "서버 뮤트", server_unmute: "서버 뮤트 해제",
  server_media_mute: "미디어 뮤트", server_unmedia_mute: "미디어 뮤트 해제",
  server_purge: "서버 삭제",
};

export default function RemoteServerDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [server, setServer] = useState<ServerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [logs, setLogs] = useState<ModLog[]>([]);
  const [users, setUsers] = useState<RemoteUser[]>([]);
  const [userOffset, setUserOffset] = useState(0);
  const [hasMoreUsers, setHasMoreUsers] = useState(false);
  const [loadingUsers, setLoadingUsers] = useState(false);

  const domain = typeof params.domain === "string" ? params.domain : "";

  const loadUsers = async (append = false) => {
    const offset = append ? userOffset : 0;
    setLoadingUsers(true);
    try {
      const res = await fetch(`/api/admin/remote-server/${encodeURIComponent(domain)}?offset=${offset}&limit=20`, { credentials: "include" });
      if (res.ok) {
        const d = await res.json();
        if (append) {
          setUsers(prev => [...prev, ...d.users]);
        } else {
          setUsers(d.users || []);
        }
        setUserOffset(offset + d.users.length);
        setHasMoreUsers(d.has_more || false);
      }
    } catch {}
    setLoadingUsers(false);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [serverRes, logsRes] = await Promise.all([
        fetch(`/api/admin/remote-server/${encodeURIComponent(domain)}?offset=0&limit=20`, { credentials: "include" }),
        fetch(`/api/admin/logs?target_type=domain&target_username=${encodeURIComponent(domain)}&limit=20`, { credentials: "include" }),
      ]);
      if (serverRes.ok) {
        const d = await serverRes.json();
        setServer(d);
        setUsers(d.users || []);
        setUserOffset(d.users.length);
        setHasMoreUsers(d.has_more || false);
      } else {
        setError("서버 정보를 불러올 수 없습니다.");
      }
      if (logsRes.ok) {
        const d = await logsRes.json();
        setLogs(d.logs || []);
      }
    } catch {
      setError("오류가 발생했습니다.");
    }
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading && !isStaff(user)) {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!authLoading && domain) {
      let cancelled = false;
      (async () => {
        try {
          const [serverRes, logsRes] = await Promise.all([
            fetch(`/api/admin/remote-server/${encodeURIComponent(domain)}?offset=0&limit=20`, { credentials: "include" }),
            fetch(`/api/admin/logs?target_type=domain&target_username=${encodeURIComponent(domain)}&limit=20`, { credentials: "include" }),
          ]);
          if (serverRes.ok) {
            const d = await serverRes.json();
            if (!cancelled) {
              setServer(d);
              setUsers(d.users || []);
              setUserOffset(d.users.length);
              setHasMoreUsers(d.has_more || false);
            }
          } else if (!cancelled) {
            setError("서버 정보를 불러올 수 없습니다.");
          }
          if (logsRes.ok) {
            const d = await logsRes.json();
            if (!cancelled) setLogs(d.logs || []);
          }
        } catch {
          if (!cancelled) setError("오류가 발생했습니다.");
        }
        if (!cancelled) setLoading(false);
      })();
      return () => { cancelled = true; };
    }
  }, [domain, authLoading]);

  const doAction = async (action: string, confirmMsg: string) => {
    if (!confirm(confirmMsg)) return;
    setMsg("");
    try {
      const res = await fetch(`/api/admin/remote-server/${encodeURIComponent(domain)}/${action}`, {
        method: "POST", credentials: "include",
      });
      const text = await res.text();
      let d;
      try { d = JSON.parse(text); } catch { d = { detail: text }; }
      if (res.ok) {
        if (action === "purge") {
          router.push("/admin/federation");
          return;
        }
        setMsg(d.message || "완료되었습니다.");
        load();
      } else {
        setMsg(d.detail || text || "실패했습니다.");
      }
    } catch (e) {
      setMsg("오류: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const isMod = can(user, PERMS.federationManage);
  const isAdmin = can(user, PERMS.federationMode);

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || !isStaff(user)) return null;
  if (error) return <><div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div><AdminNav current="federation" user={user} /><div className="empty-state">{error}</div></>;
  if (!server) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="federation" user={user} />

      <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 20 }}>
        <img
          src={server.server_icon}
          alt=""
          style={{ width: 48, height: 48, borderRadius: 10, objectFit: "cover", background: "var(--bg-tertiary)" }}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
        <div>
          <div style={{ fontWeight: 600, fontSize: "1.1em" }}>{server.domain}</div>
          <div style={{ display: "flex", gap: 16, fontSize: "0.85em", color: "var(--text-muted)", marginTop: 4 }}>
            <span>유저 {server.total_users}명</span>
            <span>팔로우 {server.local_following}</span>
            <span>팔로워 {server.local_followers}</span>
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <StatusBadge active={server.is_blocked} label="차단" color="var(--danger)" />
          <StatusBadge active={server.is_muted} label="뮤트" color="#e67e22" />
          <StatusBadge active={server.is_media_muted} label="미디어 뮤트" color="#e67e22" />
          <span className="badge" style={{ background: server.is_reachable ? "var(--success)" : "var(--danger)", color: "#fff", padding: "4px 10px", borderRadius: 6, fontSize: "0.8em" }}>
            {server.is_reachable ? "접속 가능" : "접속 불가"}
          </span>
        </div>
      </div>

      {msg && (
        <div style={{ padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 6, marginBottom: 16, fontSize: "0.85em" }}>
          {msg}
        </div>
      )}

      <div className="novel-form" style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>작업</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isAdmin && (
            <ActionButton
              label={server.is_blocked ? "차단 해제" : "서버 차단"}
              color={server.is_blocked ? "#888" : "var(--danger)"}
              onClick={() => doAction(server.is_blocked ? "unblock" : "block",
                server.is_blocked ? "이 서버의 차단을 해제하시겠습니까?" : "이 서버를 차단하시겠습니까?\n해당 서버의 모든 사용자와 게시물이 차단됩니다.")}
            />
          )}
          {isMod && (
            <>
              <ActionButton
                label={server.is_muted ? "뮤트 해제" : "서버 뮤트"}
                color={server.is_muted ? "#888" : "#e67e22"}
                onClick={() => doAction(server.is_muted ? "unmute" : "mute",
                  server.is_muted ? "이 서버의 뮤트를 해제하시겠습니까?\n공개 게시글이 다시 공개 표시됩니다." : "이 서버를 뮤트하시겠습니까?\n공개 설정 게시글이 홈 전용으로 표시됩니다.")}
              />
              <ActionButton
                label={server.is_media_muted ? "미디어 뮤트 해제" : "미디어 뮤트"}
                color={server.is_media_muted ? "#888" : "#e67e22"}
                onClick={() => doAction(server.is_media_muted ? "unmedia-mute" : "media-mute",
                  server.is_media_muted ? "미디어 뮤트를 해제하시겠습니까?" : "모든 미디어를 민감함으로 표시하시겠습니까?")}
              />
            </>
          )}
          {isAdmin && (
            <button
              onClick={() => doAction("purge", "정말로 이 서버의 모든 데이터를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없습니다!")}
              className="btn btn-small"
              style={{ background: "var(--danger)", color: "#fff", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: "0.85em" }}
            >
              <Icon name="trash" /> 서버 삭제 (Purge)
            </button>
          )}
        </div>
      </div>

      <div className="novel-form" style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>중재 기록 ({logs.length})</div>
        {logs.length === 0 ? <p className="form-help">기록이 없습니다.</p> : (
          <div className="admin-table" style={{ display: "block" }}>
            <div className="admin-table-header">
              <span style={{ width: 140, flexShrink: 0 }}>시간</span>
              <span style={{ width: 80, flexShrink: 0 }}>진행자</span>
              <span style={{ width: 100, flexShrink: 0 }}>액션</span>
              <span style={{ flex: "1 1 0", minWidth: 0 }}>상세</span>
            </div>
            {logs.map((log: ModLog) => (
              <div key={log.id} className="admin-table-row">
                <span style={{ width: 140, flexShrink: 0, fontSize: "0.85em", fontFamily: "monospace" }}>{log.created_at?.slice(0, 19) || "-"}</span>
                <span style={{ width: 80, flexShrink: 0 }}>{log.username || "-"}</span>
                <span style={{ width: 100, flexShrink: 0 }}>{actionLabels[log.action] || log.action}</span>
                <span style={{ flex: "1 1 0", minWidth: 0, fontSize: "0.85em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{log.details || "-"}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="novel-form" style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>원격 유저 목록 ({server.total_users_count})</div>
        <div className="admin-table" style={{ display: "block" }}>
          <div className="admin-table-header">
            <span style={{ flex: "1 1 0", minWidth: 0 }}>유저</span>
            <span style={{ width: 100, flexShrink: 0 }}> </span>
          </div>
          {users.map((u) => (
            <div key={u.id} className="admin-table-row">
              <span style={{ flex: "1 1 0", minWidth: 0, display: "flex", alignItems: "center", gap: 8 }}>
                {u.profile_image ? (
                  <img
                    src={u.profile_image}
                    alt=""
                    style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover" }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ) : null}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {u.display_name || u.username}
                </span>
              </span>
              <span style={{ width: 100, flexShrink: 0 }}>
                <Link href={`/admin/users/${u.id}`} className="btn btn-small btn-outline">방문</Link>
              </span>
            </div>
          ))}
        </div>
        {hasMoreUsers && (
          <div className="form-actions" style={{ marginTop: 8 }}>
            <button onClick={() => loadUsers(true)} className="btn btn-outline" disabled={loadingUsers}>
              {loadingUsers ? "로딩 중..." : "더 보기"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}

function StatusBadge({ active, label, color }: { active: boolean; label: string; color: string }) {
  if (!active) return null;
  return (
    <span className="badge" style={{ background: color, color: "#fff", padding: "4px 10px", borderRadius: 6, fontSize: "0.8em" }}>
      {label}
    </span>
  );
}

function ActionButton({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="btn btn-small"
      style={{ background: color, color: "#fff", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: "0.85em" }}
    >
      {label}
    </button>
  );
}
