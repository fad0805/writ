"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

export default function AdminSettingsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [serverName, setServerName] = useState("");
  const [logo, setLogo] = useState("");
  const [favicon, setFavicon] = useState("");
  const [appIcon, setAppIcon] = useState("");
  const [adminIds, setAdminIds] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const [fedMode, setFedMode] = useState("blacklist");
  const [blocks, setBlocks] = useState<{ id: number; domain: string; created_by: string; created_at: string }[]>([]);
  const [allows, setAllows] = useState<{ id: number; domain: string; created_by: string; created_at: string }[]>([]);
  const [addDomain, setAddDomain] = useState("");
  const [addTarget, setAddTarget] = useState<"block" | "allow">("block");

  const loadFedData = async () => {
    try {
      const modeRes = await fetch("/api/admin/federation-mode", { credentials: "include" });
      if (modeRes.ok) { const md = await modeRes.json(); setFedMode(md.mode || "blacklist"); }
      const blocksRes = await fetch("/api/admin/federation-blocks", { credentials: "include" });
      if (blocksRes.ok) { const bd = await blocksRes.json(); setBlocks(bd.blocks || []); }
      const allowsRes = await fetch("/api/admin/allowed-servers", { credentials: "include" });
      if (allowsRes.ok) { const ad = await allowsRes.json(); setAllows(ad.servers || []); }
    } catch {}
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (authLoading) return;
    fetch("/api/admin/settings", { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        setServerName(d.server_name || "");
        setLogo(d.logo || "");
        setFavicon(d.favicon || "");
        setAppIcon(d.app_icon || "");
        setAdminIds(d.admin_ids || "");
        setAdminEmail(d.admin_email || "");
        setLoading(false);
      })
      .catch(() => setLoading(false));
    loadFedData();
  }, [authLoading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const form = new FormData();
      form.append("server_name", serverName);
      form.append("logo", logo);
      form.append("favicon", favicon);
      form.append("app_icon", appIcon);
      form.append("admin_ids", adminIds);
      form.append("admin_email", adminEmail);
      const res = await fetch("/api/admin/settings", { method: "POST", credentials: "include", body: form });
      if (res.ok) { setMsg("저장되었습니다."); window.dispatchEvent(new Event("serverchange")); }
      else setMsg("저장 실패");
    } catch { setMsg("오류 발생"); }
    setSaving(false);
  };

  const handleModeChange = async (mode: string) => {
    const form = new FormData();
    form.append("mode", mode);
    const res = await fetch("/api/admin/federation-mode", { method: "POST", credentials: "include", body: form });
    if (res.ok) { setFedMode(mode); setMsg(`연합 모드가 ${mode === "whitelist" ? "화이트리스트" : "블랙리스트"}(으)로 변경되었습니다.`); }
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
      <AdminNav current="settings" />
      {msg && <p style={{ marginBottom: 12, color: "var(--accent)", fontWeight: 600 }}>{msg}</p>}

      <form onSubmit={handleSubmit} className="novel-form" style={{ marginBottom: 20 }}>
        <div className="form-group">
          <label>서버 이름</label>
          <input type="text" value={serverName} onChange={(e) => setServerName(e.target.value.slice(0, 20))} className="cw-input" placeholder="WRIT" maxLength={20} />
          <p className="form-help">최대 20자까지 입력 가능합니다.</p>
        </div>
        <div className="form-group">
          <label>대표 아이콘 (URL)</label>
          <input type="text" value={logo} onChange={(e) => setLogo(e.target.value)} className="cw-input" placeholder="https://example.com/logo.png" />
          {logo && <img src={logo} alt="logo" style={{ maxWidth: 80, maxHeight: 80, marginTop: 8, borderRadius: 8 }} />}
        </div>
        <div className="form-group">
          <label>파비콘 (URL)</label>
          <input type="text" value={favicon} onChange={(e) => setFavicon(e.target.value)} className="cw-input" placeholder="https://example.com/favicon.ico" />
        </div>
        <div className="form-group">
          <label>모바일 앱 아이콘 (URL)</label>
          <input type="text" value={appIcon} onChange={(e) => setAppIcon(e.target.value)} className="cw-input" placeholder="https://example.com/app-icon.png" />
        </div>
        <div className="form-group">
          <label>관리자 계정</label>
          <input type="text" value={adminIds} onChange={(e) => setAdminIds(e.target.value)} className="cw-input" placeholder="owner" />
          <p className="form-help">서버 정보에 표시할 관리자 계정 핸들을 입력하세요. 기본값은 owner입니다.</p>
        </div>
        <div className="form-group">
          <label>관리 이메일</label>
          <input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} className="cw-input" placeholder="admin@example.com" />
          <p className="form-help">서버 정보에 표시할 관리 이메일 주소입니다. 비워두면 설정된 관리자 계정의 이메일이 표시됩니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "저장 중..." : "저장"}</button>
        </div>
      </form>

      <div className="novel-form" style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: "1.1em", marginBottom: 16 }}><Icon name="globe" /> 연합 (ActivityPub)</h3>
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
