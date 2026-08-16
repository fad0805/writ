"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/permissions";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

type PermissionInfo = { label: string; tier: "admin" | "moderation" };
type RoleInfo = { name: string; label: string; permissions: string[] };

const BUILTIN_ROLES = new Set(["owner", "admin", "moderator", "user"]);

export default function AdminRolesPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [catalog, setCatalog] = useState<Record<string, PermissionInfo>>({});
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Set<string>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!authLoading && !isStaff(user))
      router.push("/timeline/home");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (authLoading) return;
    fetch("/api/admin/roles", { credentials: "include" })
      .then(r => r.json())
      .then(d => {
        setCatalog(d.catalog || {});
        setRoles(d.roles || []);
        const drafts: Record<string, Set<string>> = {};
        for (const r of d.roles || []) drafts[r.name] = new Set(r.permissions || []);
        setDrafts(drafts);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [authLoading]);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || !isStaff(user)) return null;

  const tierOrder = ["moderation", "admin"] as const;
  const tierLabel: Record<string, string> = { moderation: "중재", admin: "관리" };

  const reload = () => {
    setLoading(true);
    setMsg("");
    fetch("/api/admin/roles", { credentials: "include" })
      .then(r => r.json())
      .then(d => {
        setRoles(d.roles || []);
        const drafts: Record<string, Set<string>> = {};
        for (const r of d.roles || []) drafts[r.name] = new Set(r.permissions || []);
        setDrafts(drafts);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  const toggle = (roleName: string, perm: string) => {
    const next = new Set(drafts[roleName] || []);
    if (next.has(perm)) next.delete(perm); else next.add(perm);
    setDrafts({ ...drafts, [roleName]: next });
    setMsg("");
    setErr("");
  };

  const save = async (roleName: string) => {
    setSaving(roleName);
    setMsg("");
    setErr("");
    try {
      const res = await fetch(`/api/admin/roles/${roleName}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permissions: Array.from(drafts[roleName] || []) }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "저장 실패");
      setRoles(roles.map(r => (r.name === roleName ? { ...r, permissions: d.permissions } : r)));
      setMsg(`${roles.find(r => r.name === roleName)?.label || roleName} 권한이 저장되었습니다.`);
    } catch (e: any) {
      setErr(e.message || "저장 실패");
    } finally {
      setSaving(null);
    }
  };

  const create = async () => {
    setCreating(true);
    setMsg("");
    setErr("");
    try {
      const res = await fetch("/api/admin/roles", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName, label: newLabel, permissions: [] }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "역할 추가 실패");
      setNewName("");
      setNewLabel("");
      setShowCreate(false);
      setMsg(`'${d.role.label}' 역할이 추가되었습니다.`);
      reload();
    } catch (e: any) {
      setErr(e.message || "역할 추가 실패");
    } finally {
      setCreating(false);
    }
  };

  const remove = async (role: RoleInfo) => {
    if (!window.confirm(`'${role.label}' 역할을 삭제할까요?`)) return;
    setSaving(role.name);
    setMsg("");
    setErr("");
    try {
      const res = await fetch(`/api/admin/roles/${role.name}`, { method: "DELETE", credentials: "include" });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "역할 삭제 실패");
      setMsg(`'${role.label}' 역할이 삭제되었습니다.`);
      reload();
    } catch (e: any) {
      setErr(e.message || "역할 삭제 실패");
      setSaving(null);
    }
  };

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="roles" user={user} />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
          역할별 권한을 설정합니다. 변경 사항은 저장 직후 적용됩니다. 서버 소유자(owner) 역할은 항상 모든 권한을 가집니다.
        </p>
        <button onClick={() => { setShowCreate(!showCreate); setErr(""); }} className="btn btn-small btn-primary">역할 추가</button>
      </div>

      {showCreate && (
        <div className="admin-search-panel" style={{ marginBottom: 12 }}>
          <div className="admin-search-fields">
            <div>
              <label>역할 키</label>
              <input type="text" value={newName} onChange={e => setNewName(e.target.value)} placeholder="예: helper (영문 소문자/숫자/밑줄 2~15자)" className="cw-input" />
            </div>
            <div>
              <label>표시 이름</label>
              <input type="text" value={newLabel} onChange={e => setNewLabel(e.target.value)} placeholder="예: 도우미" className="cw-input" />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
              <button onClick={create} disabled={creating} className="btn btn-small btn-primary">{creating ? "추가 중..." : "추가"}</button>
              <button onClick={() => { setShowCreate(false); setErr(""); }} className="btn btn-small btn-outline">취소</button>
            </div>
          </div>
        </div>
      )}

      {msg && <div style={{ fontSize: 13, color: "var(--accent)", marginBottom: 12 }}>{msg}</div>}
      {err && <div style={{ fontSize: 13, color: "#e74c3c", marginBottom: 12 }}>{err}</div>}

      {loading ? <div className="empty-state">로딩 중...</div>
      : roles.length === 0 ? <div className="empty-state">역할 정보가 없습니다.</div>
      : <div className="role-grid">
          {roles.map(role => {
            const perms = drafts[role.name] || new Set<string>();
            return (
              <div key={role.name} className="role-card">
                <div className="role-card-header">
                  <div>
                    <div className="role-card-title">{role.label}</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      @{role.name} · <span className="role-perm-count">{perms.size}개 권한</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {role.name !== "owner" && (
                      <button onClick={() => save(role.name)} disabled={saving === role.name} className="btn btn-primary btn-small">
                        {saving === role.name ? "저장 중..." : "저장"}
                      </button>
                    )}
                    {!BUILTIN_ROLES.has(role.name) && (
                      <button onClick={() => remove(role)} disabled={saving === role.name} className="btn btn-small btn-outline" style={{ color: "#e74c3c" }} title="역할 삭제">삭제</button>
                    )}
                  </div>
                </div>
                <div className="role-card-body">
                  {role.name === "owner" ? (
                    <div style={{ fontSize: 13, color: "var(--text-muted)", padding: "4px 0" }}>모든 권한 보유 (변경 불가)</div>
                  ) : (
                    tierOrder.map(tier => (
                      <div key={tier} style={{ marginTop: 4 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>{tierLabel[tier]}</div>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                          {Object.entries(catalog).filter(([, info]) => info.tier === tier).map(([perm, info]) => (
                            <label key={perm} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px", background: "var(--bg-primary)" }}>
                              <input type="checkbox" checked={perms.has(perm)} onChange={() => toggle(role.name, perm)} />
                              {info.label}
                            </label>
                          ))}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>}
    </>
  );
}
