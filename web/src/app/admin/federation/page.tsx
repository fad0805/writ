"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

export default function AdminFederationPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [fedMode, setFedMode] = useState("blacklist");
  const [blocks, setBlocks] = useState<{ id: number; domain: string; created_by: string; created_at: string }[]>([]);
  const [allows, setAllows] = useState<{ id: number; domain: string; created_by: string; created_at: string }[]>([]);
  const [addDomain, setAddDomain] = useState("");
  const [addTarget, setAddTarget] = useState<"block" | "allow">("block");
  const [loading, setLoading] = useState(true);

  const loadFedData = async () => {
    try {
      const modeRes = await fetch("/api/admin/federation-mode", { credentials: "include" });
      if (modeRes.ok) { const md = await modeRes.json(); setFedMode(md.mode || "blacklist"); }
      const blocksRes = await fetch("/api/admin/federation-blocks", { credentials: "include" });
      if (blocksRes.ok) { const bd = await blocksRes.json(); setBlocks(bd.blocks || []); }
      const allowsRes = await fetch("/api/admin/allowed-servers", { credentials: "include" });
      if (allowsRes.ok) { const ad = await allowsRes.json(); setAllows(ad.servers || []); }
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (authLoading) return;
    loadFedData();
  }, [authLoading]);

  const handleModeChange = async (mode: string) => {
    const form = new FormData();
    form.append("mode", mode);
    const res = await fetch("/api/admin/federation-mode", { method: "POST", credentials: "include", body: form });
    if (res.ok) { setFedMode(mode); }
    else { const d = await res.json().catch(() => ({})); alert(d.detail || "실패"); }
  };

  const handleAddDomain = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addDomain.trim()) return;
    const endpoint = addTarget === "block" ? "/api/admin/federation-block" : "/api/admin/allowed-server";
    const form = new FormData();
    form.append("domain", addDomain.trim().toLowerCase());
    const res = await fetch(endpoint, { method: "POST", credentials: "include", body: form });
    const d = await res.json().catch(() => ({}));
    if (res.ok) { setAddDomain(""); loadFedData(); }
    else { alert(d.detail || "실패"); }
  };

  const handleRemoveBlock = async (domain: string) => {
    const res = await fetch(`/api/admin/federation-block/${encodeURIComponent(domain)}`, { method: "DELETE", credentials: "include" });
    if (res.ok) loadFedData();
    else { const d = await res.json().catch(() => ({})); alert(d.detail || "실패"); }
  };

  const handleRemoveAllow = async (domain: string) => {
    const res = await fetch(`/api/admin/allowed-server/${encodeURIComponent(domain)}`, { method: "DELETE", credentials: "include" });
    if (res.ok) loadFedData();
    else { const d = await res.json().catch(() => ({})); alert(d.detail || "실패"); }
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="federation" />

      <div className="novel-form">
        <h3 style={{ fontSize: "1.1em", marginBottom: 16 }}><Icon name="globe" /> 연합</h3>
        <div className="form-group">
          <label>연합 모드</label>
          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <button onClick={() => handleModeChange("blacklist")} className={`btn btn-small ${fedMode === "blacklist" ? "btn-primary" : "btn-outline"}`}>블랙리스트</button>
            <button onClick={() => handleModeChange("whitelist")} className={`btn btn-small ${fedMode === "whitelist" ? "btn-primary" : "btn-outline"}`}>화이트리스트</button>
          </div>
          <p className="form-help">
            {fedMode === "blacklist"
              ? "차단된 서버를 제외한 모든 서버와 연합합니다."
              : "허용된 서버만 연합합니다."}
          </p>
        </div>

        <div className="form-group">
          <label>서버 추가</label>
          <form onSubmit={handleAddDomain} style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <input type="text" value={addDomain} onChange={(e) => setAddDomain(e.target.value)} placeholder="example.com" className="cw-input" style={{ flex: 1 }} required />
            <select value={addTarget} onChange={(e) => setAddTarget(e.target.value as "block" | "allow")} className="cw-input" style={{ width: 100 }}>
              <option value="block">차단</option>
              <option value="allow">허용</option>
            </select>
            <button type="submit" className="btn btn-primary btn-small">추가</button>
          </form>
        </div>

        {fedMode === "blacklist" && blocks.length > 0 && (
          <div className="form-group">
            <label>차단된 서버 ({blocks.length})</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
              {blocks.map((b) => (
                <div key={b.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-tertiary)", borderRadius: 6 }}>
                  <span style={{ fontFamily: "monospace" }}>{b.domain}</span>
                  <button onClick={() => handleRemoveBlock(b.domain)} className="btn btn-small btn-outline text-xs" style={{ color: "var(--danger)" }}>해제</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {fedMode === "whitelist" && allows.length > 0 && (
          <div className="form-group">
            <label>허용된 서버 ({allows.length})</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
              {allows.map((a) => (
                <div key={a.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: "var(--bg-tertiary)", borderRadius: 6 }}>
                  <span style={{ fontFamily: "monospace" }}>{a.domain}</span>
                  <button onClick={() => handleRemoveAllow(a.domain)} className="btn btn-small btn-outline text-xs" style={{ color: "var(--danger)" }}>제거</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {fedMode === "blacklist" && blocks.length === 0 && <p className="form-help">차단된 서버가 없습니다.</p>}
        {fedMode === "whitelist" && allows.length === 0 && <p className="form-help">허용된 서버가 없습니다 (연합 비활성화).</p>}
      </div>
    </>
  );
}
