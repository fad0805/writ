"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";

type AdminUser = {
  id: number; username: string; display_name: string; avatar: string;
  role: string; is_remote: boolean; is_suspended?: boolean;
  post_count: number; follower_count: number;
  last_active: string; email_domain: string; recent_ips: string[];
};

function timeAgo(t: string): string {
  if (!t) return "";
  const diff = Date.now() - new Date(t).getTime();
  const days = Math.floor(diff / 86400000);
  if (days < 0) return "";
  if (days === 0) return "오늘";
  if (days === 1) return "1일 전";
  if (days < 7) return `${days}일 전`;
  return "";
}

export default function AdminUsersPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [showSearch, setShowSearch] = useState(false);

  const [searchQ, setSearchQ] = useState("");
  const [usernameQ, setUsernameQ] = useState("");
  const [emailQ, setEmailQ] = useState("");
  const [ipQ, setIpQ] = useState("");
  const [loc, setLoc] = useState("local");
  const [status, setStatus] = useState("all");
  const [role, setRole] = useState("all");
  const [sort, setSort] = useState("newest");

  const loadUsers = () => {
    setLoading(true);
    const params = new URLSearchParams({ location: loc, status, role, sort });
    if (searchQ) params.set("q", searchQ);
    if (usernameQ) params.set("username_q", usernameQ);
    if (emailQ) params.set("email_q", emailQ);
    if (ipQ) params.set("ip_q", ipQ);
    fetch(`/api/admin/users?${params}`, { credentials: "include" })
      .then(r => r.json()).then(d => { setUsers(d.users); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator")
      router.push("/timeline/home");
  }, [user, authLoading, router]);

  useEffect(() => { if (!authLoading) loadUsers(); }, [authLoading, loc, status, role, sort]);

  const toggleAll = () => {
    if (selected.size === users.length) setSelected(new Set());
    else setSelected(new Set(users.map(u => u.id)));
  };
  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };
  const suspendSelected = async () => {
    if (selected.size === 0) return;
    await fetch("/api/admin/users/suspend", { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ user_ids: Array.from(selected).join(",") }) });
    loadUsers(); setSelected(new Set());
  };
  const unsuspendSelected = async () => {
    if (selected.size === 0) return;
    await fetch("/api/admin/users/unsuspend", { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ user_ids: Array.from(selected).join(",") }) });
    loadUsers(); setSelected(new Set());
  };

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <div className="admin-tabs" style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        <Link href="/admin" className="btn btn-outline btn-small">대시보드</Link>
        <Link href="/admin/users" className="btn btn-primary btn-small">유저 관리</Link>
        <Link href="/admin/emojis" className="btn btn-outline btn-small">커스텀 이모지</Link>
      </div>

      <div style={{ marginBottom: 12 }}>
        <button onClick={() => setShowSearch(!showSearch)} className="btn btn-outline btn-small" style={{ marginBottom: 8 }}>
          검색/필터 {showSearch ? "▲" : "▼"}
        </button>

        {showSearch && (
          <div style={{ padding: "12px 14px", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 8, fontSize: "0.85em" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
              <div><label style={{ display: "block", marginBottom: 3, color: "var(--text-muted)" }}>아이디/이름</label><input type="text" value={usernameQ} onChange={e => setUsernameQ(e.target.value)} placeholder="username 또는 이름" className="cw-input" style={{ width: "100%" }} /></div>
              <div><label style={{ display: "block", marginBottom: 3, color: "var(--text-muted)" }}>이메일</label><input type="text" value={emailQ} onChange={e => setEmailQ(e.target.value)} placeholder="email@example.com" className="cw-input" style={{ width: "100%" }} /></div>
              <div><label style={{ display: "block", marginBottom: 3, color: "var(--text-muted)" }}>IP</label><input type="text" value={ipQ} onChange={e => setIpQ(e.target.value)} placeholder="192.168.x.x" className="cw-input" style={{ width: "100%" }} /></div>
              <div><label style={{ display: "block", marginBottom: 3, color: "var(--text-muted)" }}>통합 검색</label><input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="전체 검색" className="cw-input" style={{ width: "100%" }} /></div>
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              <label>위치 <select value={loc} onChange={e => setLoc(e.target.value)} className="cw-input" style={{ width: 90 }}><option value="all">모두</option><option value="local">로컬</option><option value="remote">리모트</option></select></label>
              <label>상태 <select value={status} onChange={e => setStatus(e.target.value)} className="cw-input" style={{ width: 100 }}>
                <option value="all">모두</option><option value="active">활성</option><option value="suspended">정지</option><option value="pending">인증대기</option><option value="inactive">비활성</option>
              </select></label>
              <label>역할 <select value={role} onChange={e => setRole(e.target.value)} className="cw-input" style={{ width: 90 }}>
                <option value="all">모두</option><option value="user">유저</option><option value="moderator">조율자</option><option value="admin">관리자</option>
              </select></label>
              <label>정렬 <select value={sort} onChange={e => setSort(e.target.value)} className="cw-input" style={{ width: 110 }}>
                <option value="newest">최신순</option><option value="active">최근활동순</option>
              </select></label>
              <button onClick={loadUsers} className="btn btn-primary btn-small">검색</button>
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={suspendSelected} disabled={selected.size === 0} className="btn btn-small" style={{ background: "var(--danger)", color: "#fff", border: "none" }}>정지</button>
        <button onClick={unsuspendSelected} disabled={selected.size === 0} className="btn btn-small btn-outline">정지 해제</button>
      </div>

      {loading ? <div className="empty-state">로딩 중...</div>
      : users.length === 0 ? <div className="empty-state">사용자가 없습니다.</div>
      : <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85em" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                <th style={{ padding: "8px 10px", textAlign: "left", width: 36 }}><input type="checkbox" checked={selected.size === users.length && users.length > 0} onChange={toggleAll} /></th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>사용자</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>게시물</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>팔로워</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>최근 활동</th>
                <th style={{ padding: "8px 10px", textAlign: "left" }}>이메일/IP</th>
                <th style={{ padding: "8px 10px", textAlign: "center" }}>상태</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid var(--border)", background: selected.has(u.id) ? "var(--card-hover)" : "transparent", opacity: u.is_suspended ? 0.5 : 1 }}>
                  <td style={{ padding: "10px" }}><input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} /></td>
                  <td style={{ padding: "10px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ width: 32, height: 32, borderRadius: 6, background: `hsl(${hashStr(u.username)}, 35%, 45%)`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", fontSize: "0.85em", flexShrink: 0 }}>
                        {(u.display_name || u.username)[0]}
                      </div>
                      <div>
                        <Link href={`/admin/users/${u.id}`} style={{ textDecoration: "none" }}>
                          <div style={{ fontWeight: 600, color: "var(--text-primary)", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {u.display_name}
                            {u.role === "admin" && <Icon name="shield_filled" style={{ color: "#27ae60", fontSize: "0.6em", verticalAlign: "middle", marginLeft: 3 }} title="관리자" />}
                            {u.role === "moderator" && <Icon name="shield_filled" style={{ color: "#cc8800", fontSize: "0.6em", verticalAlign: "middle", marginLeft: 3 }} title="조율자" />}
                          </div>
                        </Link>
                        <div style={{ fontSize: "0.85em", color: "var(--text-dim)" }}>@{u.username}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{u.post_count}</td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{u.follower_count}</td>
                  <td style={{ padding: "10px", textAlign: "center", color: "var(--text-secondary)" }}>{timeAgo(u.last_active) || "-"}</td>
                  <td style={{ padding: "10px", color: "var(--text-dim)", fontSize: "0.85em" }}>
                    {u.email_domain || "-"}
                    {u.recent_ips && u.recent_ips.length > 0 && <span style={{ fontFamily: "monospace", marginLeft: 4 }}>/ {u.recent_ips[0]}</span>}
                  </td>
                  <td style={{ padding: "10px", textAlign: "center" }}>
                    {u.is_suspended ? <span style={{ color: "var(--danger)", fontSize: "0.85em" }}>정지</span>
                    : u.is_remote ? <span style={{ color: "var(--text-dim)", fontSize: "0.85em" }}>리모트</span>
                    : <span style={{ color: "var(--accent)", fontSize: "0.85em" }}>활성</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    </>
  );
}

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h);
  return ((h % 360) + 360) % 360;
}
