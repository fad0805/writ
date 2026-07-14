"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

type AdminUser = {
  id: number; username: string; display_name: string; avatar: string;
  role: string; is_remote: boolean; is_suspended?: boolean; is_frozen?: boolean; is_limited?: boolean; is_deceased?: boolean;
  email_verified?: boolean;
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

  const [usernameQ, setUsernameQ] = useState("");
  const [nameQ, setNameQ] = useState("");
  const [emailQ, setEmailQ] = useState("");
  const [ipQ, setIpQ] = useState("");
  const [domainQ, setDomainQ] = useState("");
  const [loc, setLoc] = useState("local");
  const [status, setStatus] = useState("all");
  const [role, setRole] = useState("all");
  const [sort, setSort] = useState("newest");

  const loadUsers = () => {
    setLoading(true);
    const params = new URLSearchParams({ location: loc, status, role, sort });
    if (usernameQ) params.set("username_q", usernameQ);
    if (nameQ) params.set("name_q", nameQ);
    if (emailQ) params.set("email_q", emailQ);
    if (ipQ) params.set("ip_q", ipQ);
    if (domainQ) params.set("domain_q", domainQ);
    fetch(`/api/admin/users?${params}`, { credentials: "include" })
      .then(r => r.json()).then(d => { setUsers(d.users); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner")
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
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="users" />

      <div className="admin-users-container">
        <div className="admin-action-bar">
          <button onClick={suspendSelected} disabled={selected.size === 0} className="btn btn-small btn-moderate">정지</button>
          <button onClick={unsuspendSelected} disabled={selected.size === 0} className="btn btn-small btn-outline">정지 해제</button>
          <div className="admin-spacer" />
          <button onClick={() => setShowSearch(!showSearch)} className="btn btn-outline btn-small">
            검색/필터 {showSearch ? "▲" : "▼"}
          </button>
        </div>

        {showSearch && (
          <div className="admin-search-panel">
            <div className="admin-search-fields">
              <div><label>아이디</label><input type="text" value={nameQ} onChange={e => setNameQ(e.target.value)} placeholder="표시 이름" className="cw-input" /></div>
              <div><label>유저명</label><input type="text" value={usernameQ} onChange={e => setUsernameQ(e.target.value)} placeholder="@username" className="cw-input" /></div>
              <div><label>이메일</label><input type="text" value={emailQ} onChange={e => setEmailQ(e.target.value)} placeholder="email@example.com" className="cw-input" /></div>
              <div><label>IP</label><input type="text" value={ipQ} onChange={e => setIpQ(e.target.value)} placeholder="192.168.x.x" className="cw-input" /></div>
              {loc === "remote" && <div><label>도메인</label><input type="text" value={domainQ} onChange={e => setDomainQ(e.target.value)} placeholder="example.com" className="cw-input" /></div>}
            </div>
            <div className="admin-filter-row">
              <label>위치 <select value={loc} onChange={e => setLoc(e.target.value)} className="cw-input select-w-90"><option value="all">모두</option><option value="local">로컬</option><option value="remote">리모트</option></select></label>
              <label>상태 <select value={status} onChange={e => setStatus(e.target.value)} className="cw-input select-w-100">
                <option value="all">모두</option><option value="active">활성</option><option value="suspended">정지</option><option value="pending">인증대기</option><option value="inactive">비활성</option>
              </select></label>
              <label>역할 <select value={role} onChange={e => setRole(e.target.value)} className="cw-input select-w-110">
                <option value="all">모두</option><option value="user">유저</option><option value="moderator">조율자</option><option value="admin">관리자</option><option value="owner">오너</option>
              </select></label>
              <label>정렬 <select value={sort} onChange={e => setSort(e.target.value)} className="cw-input select-w-110">
                <option value="newest">최신순</option><option value="active">최근활동순</option>
              </select></label>
              <button onClick={loadUsers} className="btn btn-primary btn-small">검색</button>
            </div>
          </div>
        )}
      </div>

      {loading ? <div className="empty-state">로딩 중...</div>
      : users.length === 0 ? <div className="empty-state">사용자가 없습니다.</div>
      : <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr className="admin-tr text-muted">
                <th className="admin-th-checkbox"><input type="checkbox" checked={selected.size === users.length && users.length > 0} onChange={toggleAll} /></th>
                <th>사용자</th>
                <th className="text-center">게시물</th>
                <th className="text-center">팔로워</th>
                <th className="text-center">최근 활동</th>
                <th>이메일/IP</th>
                <th className="text-center">상태</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid var(--border)", background: selected.has(u.id) ? "var(--card-hover)" : "transparent", opacity: u.is_suspended ? 0.5 : (u.is_frozen ? 0.5 : (!u.email_verified && !u.is_remote ? 0.5 : (u.is_limited ? 0.7 : (u.is_deceased ? 0.7 : 1)))) }}>
                  <td style={{ padding: "10px" }}><input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} /></td>
                  <td style={{ padding: "10px" }}>
                    <div className="flex-center gap-10">
                      {u.avatar ? (
                        <img src={u.avatar} alt="" className="admin-user-avatar" style={{ objectFit: "cover" }} />
                      ) : (
                        <div className="admin-user-avatar" style={{ background: `hsl(${hashStr(u.username)}, 35%, 45%)` }}>
                          {(u.display_name || u.username)[0]}
                        </div>
                      )}
                      <div>
                        <Link href={`/admin/users/${u.id}`} style={{ textDecoration: "none" }}>
                          <div className="admin-user-name">
                            {u.display_name}
                            {u.role === "owner" && <Icon name="books_solid" className="icon-badge-sm" style={{ marginLeft: 3, color: "var(--accent)" }} title="오너" />}
                            {u.role === "admin" && <Icon name="shield_filled" className="icon-badge-sm icon-admin" style={{ marginLeft: 3 }} title="관리자" />}
                            {u.role === "moderator" && <Icon name="shield_filled" className="icon-badge-sm icon-mod" style={{ marginLeft: 3 }} title="조율자" />}
                          </div>
                        </Link>
                        <div className="admin-user-handle">@{u.username}</div>
                      </div>
                    </div>
                  </td>
                  <td className="admin-td-center">{u.post_count}</td>
                  <td className="admin-td-center">{u.follower_count}</td>
                  <td className="admin-td-center">{timeAgo(u.last_active) || "-"}</td>
                  <td className="admin-td-ip">
                    {u.email_domain || "-"}
                    {u.recent_ips && u.recent_ips.length > 0 && <span className="admin-ip-mono">/ {u.recent_ips[0]}</span>}
                  </td>
                  <td className="admin-td-status">
                    {u.is_deceased ? <span className="admin-status-suspended">고인</span>
                    : u.is_suspended ? <span className="admin-status-suspended">정지</span>
                    : u.is_frozen ? <span className="admin-status-suspended">동결</span>
                    : u.is_limited ? <span className="admin-status-suspended">제한</span>
                    : !u.email_verified && !u.is_remote ? <span className="admin-status-pending">미인증</span>
                    : u.is_remote ? <span className="admin-status-remote">리모트</span>
                    : <span className="admin-status-active">활성</span>}
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
