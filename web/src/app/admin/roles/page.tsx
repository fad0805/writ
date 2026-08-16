"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

type PermissionInfo = { label: string; tier: "admin" | "moderation" };
type RoleInfo = { name: string; label: string; permissions: string[] };

export default function AdminRolesPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [catalog, setCatalog] = useState<Record<string, PermissionInfo>>({});
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Set<string>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner")
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
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  const tierOrder = ["moderation", "admin"] as const;
  const tierLabel: Record<string, string> = { moderation: "중재", admin: "관리" };

  const toggle = (roleName: string, perm: string) => {
    const next = new Set(drafts[roleName] || []);
    if (next.has(perm)) next.delete(perm); else next.add(perm);
    setDrafts({ ...drafts, [roleName]: next });
    setMsg("");
  };

  const save = async (roleName: string) => {
    setSaving(roleName);
    setMsg("");
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
      setMsg(e.message || "저장 실패");
    } finally {
      setSaving(null);
    }
  };

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="roles" />

      <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
        역할별 권한을 설정합니다. 변경 사항은 저장 직후 적용됩니다. 서버 소유자(owner) 역할은 항상 모든 권한을 가집니다.
      </p>

      {msg && <div style={{ fontSize: 13, color: "var(--accent)", marginBottom: 12 }}>{msg}</div>}

      {loading ? <div className="empty-state">로딩 중...</div>
      : roles.length === 0 ? <div className="empty-state">역할 정보가 없습니다.</div>
      : roles.map(role => (
          <div key={role.name} className="admin-detail-card" style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <h3 style={{ fontSize: 15, margin: 0 }}>
                {role.label}
                <span className="admin-ip-mono" style={{ marginLeft: 8 }}>@{role.name}</span>
              </h3>
              {role.name !== "owner" && (
                <button onClick={() => save(role.name)} disabled={saving === role.name} className="btn btn-primary btn-small">
                  {saving === role.name ? "저장 중..." : "저장"}
                </button>
              )}
            </div>
            {role.name === "owner" ? (
              <div style={{ fontSize: 13, color: "var(--text-muted)", padding: "8px 0" }}>모든 권한 보유 (변경 불가)</div>
            ) : (
              tierOrder.map(tier => (
                <div key={tier} style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>{tierLabel[tier]}</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {Object.entries(catalog).filter(([, info]) => info.tier === tier).map(([perm, info]) => (
                      <label key={perm} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px", background: "var(--bg-secondary)" }}>
                        <input type="checkbox" checked={(drafts[role.name] || new Set()).has(perm)} onChange={() => toggle(role.name, perm)} />
                        {info.label}
                      </label>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        ))}
    </>
  );
}
