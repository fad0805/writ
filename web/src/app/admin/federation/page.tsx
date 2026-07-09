"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";
import Link from "next/link";

export default function AdminFederationPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [fedMode, setFedMode] = useState("blacklist");
  const [blocks, setBlocks] = useState<{ id: number; domain: string; reason: string; created_by: string; created_at: string }[]>([]);
  const [allows, setAllows] = useState<{ id: number; domain: string; created_by: string; created_at: string }[]>([]);
  const [remoteServers, setRemoteServers] = useState<string[]>([]);
  const [addDomain, setAddDomain] = useState("");
  const [addReason, setAddReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [modeOpen, setModeOpen] = useState(false);
  const [listOpen, setListOpen] = useState(true);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const loadFedData = async () => {
    try {
      const modeRes = await fetch("/api/admin/federation-mode", { credentials: "include" });
      if (modeRes.ok) { const md = await modeRes.json(); setFedMode(md.mode || "blacklist"); }
      const blocksRes = await fetch("/api/admin/federation-blocks", { credentials: "include" });
      if (blocksRes.ok) { const bd = await blocksRes.json(); setBlocks(bd.blocks || []); }
      const allowsRes = await fetch("/api/admin/allowed-servers", { credentials: "include" });
      if (allowsRes.ok) { const ad = await allowsRes.json(); setAllows(ad.servers || []); }
      const remoteRes = await fetch("/api/admin/remote-servers", { credentials: "include" });
      if (remoteRes.ok) { const rd = await remoteRes.json(); setRemoteServers(rd.servers || []); }
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
    const endpoint = fedMode === "blacklist" ? "/api/admin/federation-block" : "/api/admin/allowed-server";
    const form = new FormData();
    form.append("domain", addDomain.trim().toLowerCase());
    if (fedMode === "blacklist") form.append("reason", addReason);
    const res = await fetch(endpoint, { method: "POST", credentials: "include", body: form });
    const d = await res.json().catch(() => ({}));
    if (res.ok) { setAddDomain(""); setAddReason(""); loadFedData(); }
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

  const q = searchQuery.trim().toLowerCase();
  const filteredServers = q ? remoteServers.filter(s => s.toLowerCase().includes(q)) : remoteServers;
  const filteredBlocks = q ? blocks.filter(b => b.domain.toLowerCase().includes(q)) : blocks;
  const filteredAllows = q ? allows.filter(a => a.domain.toLowerCase().includes(q)) : allows;

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="federation" />

      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="서버 도메인 검색..."
          className="cw-input"
          style={{ width: "100%" }}
        />
      </div>

      <div className="novel-form">
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: modeOpen ? 16 : 0, userSelect: "none" }}
          onClick={() => setModeOpen(!modeOpen)}
        >
          <span style={{ fontWeight: 600 }}>연합 모드</span>
        </div>
        {modeOpen && (
          <>
            <div className="form-group">
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
              <label>{fedMode === "blacklist" ? "서버 차단" : "서버 허용"}</label>
              <form onSubmit={handleAddDomain} style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
                <div style={{ display: "flex", gap: 6 }}>
                  <input type="text" value={addDomain} onChange={(e) => setAddDomain(e.target.value)} placeholder="example.com" className="cw-input" style={{ flex: 1 }} required />
                  <button type="submit" className="btn btn-primary btn-small">추가</button>
                </div>
                {fedMode === "blacklist" && (
                  <input type="text" value={addReason} onChange={(e) => setAddReason(e.target.value)} placeholder="차단 사유 (선택)" className="cw-input" />
                )}
              </form>
            </div>
          </>
        )}
      </div>

      <div className="novel-form" style={{ marginTop: 16 }}>
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: listOpen ? 16 : 0, userSelect: "none" }}
          onClick={() => setListOpen(!listOpen)}
        >
          <span style={{ fontWeight: 600 }}>{fedMode === "blacklist" ? "차단된 서버" : "허용된 서버"} ({fedMode === "blacklist" ? filteredBlocks.length : filteredAllows.length})</span>
        </div>
        {listOpen && (
          <>
            {fedMode === "blacklist" && (
              filteredBlocks.length === 0 ? <p className="form-help">{searchQuery ? "검색 결과가 없습니다." : "차단된 서버가 없습니다."}</p> : (
                <div className="admin-table" style={{ display: "block" }}>
                    <div className="admin-table-header">
                      <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>도메인</span>
                      <span style={{ width: 260, flexShrink: 0 }}>사유</span>
                      <span style={{ width: 60, flexShrink: 0 }}> </span>
                    </div>
                    {filteredBlocks.map((b) => (
                      <div key={b.id} className="admin-table-row">
                        <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace" }}>{b.domain}</span>
                        <span style={{ width: 260, flexShrink: 0, fontSize: "0.85em", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.reason || "-"}</span>
                        <span style={{ width: 60, flexShrink: 0 }}>
                          <button onClick={() => handleRemoveBlock(b.domain)} className="btn btn-small btn-outline" style={{ color: "var(--danger)", fontSize: "0.8em" }}>해제</button>
                        </span>
                      </div>
                    ))}
                  </div>
              )
            )}
            {fedMode === "whitelist" && (
              filteredAllows.length === 0 ? <p className="form-help">{searchQuery ? "검색 결과가 없습니다." : "허용된 서버가 없습니다 (연합 비활성화)."}</p> : (
                <div className="admin-table" style={{ display: "block" }}>
                    <div className="admin-table-header">
                      <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>도메인</span>
                      <span style={{ width: 100, flexShrink: 0 }}>허용한 사람</span>
                      <span style={{ width: 60, flexShrink: 0 }}> </span>
                    </div>
                    {filteredAllows.map((a) => (
                      <div key={a.id} className="admin-table-row">
                        <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace" }}>{a.domain}</span>
                        <span style={{ width: 100, flexShrink: 0 }}>{a.created_by || "-"}</span>
                        <span style={{ width: 60, flexShrink: 0 }}>
                          <button onClick={() => handleRemoveAllow(a.domain)} className="btn btn-small btn-outline" style={{ color: "var(--danger)", fontSize: "0.8em" }}>제거</button>
                        </span>
                      </div>
                    ))}
                  </div>
              )
            )}
          </>
        )}
      </div>

      <div className="novel-form" style={{ marginTop: 16 }}>
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: remoteOpen ? 16 : 0, userSelect: "none" }}
          onClick={() => setRemoteOpen(!remoteOpen)}
        >
          <span style={{ fontWeight: 600 }}>연동된 리모트 서버 ({filteredServers.length})</span>
        </div>
        {remoteOpen && (
          filteredServers.length === 0 ? <p className="form-help">{searchQuery ? "검색 결과가 없습니다." : "아직 연동된 리모트 서버가 없습니다."}</p> : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
              {filteredServers.map((srv) => (
                <Link
                  key={srv}
                  href={`/admin/remote-server/${encodeURIComponent(srv)}`}
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 6, textDecoration: "none", color: "inherit", fontSize: "0.85em", fontFamily: "monospace" }}
                  className="hover-bg"
                >
                  <img
                    src={`https://${srv}/favicon.ico`}
                    alt=""
                    style={{ width: 20, height: 20, borderRadius: 4, objectFit: "cover" }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                  {srv}
                </Link>
              ))}
            </div>
          )
        )}
      </div>
    </>
  );
}
