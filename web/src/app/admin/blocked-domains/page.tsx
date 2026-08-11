"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

interface BlockedDomain {
  id: number;
  domain: string;
  created_by?: string;
  created_at?: string;
}

export default function AdminBlockedDomainsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [domains, setDomains] = useState<BlockedDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [newDomain, setNewDomain] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const load = async () => {
    try {
      const res = await fetch("/api/admin/blocked-domains", { credentials: "include" });
      if (res.ok) { const d = await res.json(); setDomains(d.domains || []); }
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading) {
      let cancelled = false;
      (async () => {
        try {
          const res = await fetch("/api/admin/blocked-domains", { credentials: "include" });
          if (res.ok) { const d = await res.json(); if (!cancelled) setDomains(d.domains || []); }
        } catch {}
        if (!cancelled) setLoading(false);
      })();
      return () => { cancelled = true; };
    }
  }, [authLoading]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDomain.trim()) return;
    setMsg("");
    const form = new FormData();
    form.append("domain", newDomain.trim().toLowerCase());
    const res = await fetch("/api/admin/block-domain", { method: "POST", credentials: "include", body: form });
    const d = await res.json().catch(() => ({}));
    if (res.ok) { setNewDomain(""); setMsg(`${newDomain.trim()} 차단됨`); load(); }
    else { alert(d.detail || "실패"); }
  };

  const handleRemove = async (domain: string) => {
    const res = await fetch(`/api/admin/block-domain/${encodeURIComponent(domain)}`, { method: "DELETE", credentials: "include" });
    if (res.ok) { setMsg(`${domain} 차단 해제됨`); load(); }
    else { alert("실패"); }
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="blocked-domains" />
      {msg && <p style={{ marginBottom: 12, color: "var(--accent)", fontWeight: 600 }}>{msg}</p>}

      <form onSubmit={handleAdd} className="novel-form" style={{ marginBottom: 20 }}>
        <div className="form-group">
          <label>도메인 추가</label>
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <input type="text" value={newDomain} onChange={e => setNewDomain(e.target.value)} placeholder="example.com" className="cw-input" style={{ flex: 1 }} required />
            <button type="submit" className="btn btn-primary">차단</button>
          </div>
          <p className="form-help">해당 도메인의 이메일로는 가입할 수 없게 됩니다.</p>
        </div>
      </form>

      {domains.length === 0 ? (
        <p className="form-help">차단된 도메인이 없습니다.</p>
      ) : (
        <div className="admin-table">
          <div className="admin-table-header">
            <span style={{ flex: 1 }}>도메인</span>
            <span style={{ width: 120 }}>차단한 사람</span>
            <span style={{ width: 160 }}>차단 일시</span>
            <span style={{ width: 60 }}> </span>
          </div>
          {domains.map((d: BlockedDomain) => (
            <div key={d.id} className="admin-table-row">
              <span style={{ flex: 1, fontFamily: "monospace" }}>{d.domain}</span>
              <span style={{ width: 120 }}>{d.created_by || "-"}</span>
              <span style={{ width: 160, fontSize: "0.85em" }}>{d.created_at?.slice(0, 19) || "-"}</span>
              <span style={{ width: 60 }}>
                <button onClick={() => handleRemove(d.domain)} className="btn btn-small btn-outline" style={{ color: "var(--danger)", fontSize: "0.8em" }}>해제</button>
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
