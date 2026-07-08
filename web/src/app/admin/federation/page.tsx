"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";
import Link from "next/link";

interface SearchResult {
  source: "local" | "remote_cached" | "remote_fetched";
  id: number;
  username: string;
  display_name: string;
  profile_image: string | null;
  remote_url: string | null;
}

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
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Debounced search for @handle@domain
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q.startsWith("@") || !q.includes("@", 1)) {
      setSearchResults(null);
      setSearchError("");
      return;
    }
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      setSearchError("");
      try {
        const res = await fetch(`/api/admin/federation-search?q=${encodeURIComponent(q)}`, { credentials: "include" });
        if (res.ok) {
          const d = await res.json();
          setSearchResults(d.results || []);
        } else {
          setSearchError("검색에 실패했습니다.");
          setSearchResults([]);
        }
      } catch {
        setSearchError("네트워크 오류가 발생했습니다.");
        setSearchResults([]);
      }
      setSearching(false);
    }, 400);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [searchQuery]);

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

  const isHandleSearch = searchQuery.trim().startsWith("@") && searchQuery.trim().includes("@", 1);
  const q = isHandleSearch ? "" : searchQuery.trim().toLowerCase();
  const filteredServers = q ? remoteServers.filter(s => s.toLowerCase().includes(q)) : remoteServers;
  const filteredBlocks = q ? blocks.filter(b => b.domain.toLowerCase().includes(q)) : blocks;
  const filteredAllows = q ? allows.filter(a => a.domain.toLowerCase().includes(q)) : allows;

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  const sourceLabels: Record<string, string> = {
    local: "내 서버",
    remote_cached: "원격 (캐시됨)",
    remote_fetched: "원격 (가져옴)",
  };

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="federation" />

      <div style={{ marginBottom: 16 }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="서버 이름/도메인 검색 또는 @핸들@도메인 으로 유저 검색..."
          className="cw-input"
          style={{ width: "100%" }}
        />
        {searching && <div style={{ fontSize: "0.85em", color: "var(--text-muted)", marginTop: 4 }}>검색 중...</div>}
        {searchError && <div style={{ fontSize: "0.85em", color: "var(--danger)", marginTop: 4 }}>{searchError}</div>}
        {searchResults !== null && searchResults.length > 0 && (
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
            {searchResults.map((r) => (
              <Link
                key={r.id}
                href={r.source === "local" ? `/admin/users/${r.id}` : `/admin/remote-server/${encodeURIComponent(r.username.split("@").pop() || "")}`}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderRadius: 6, textDecoration: "none", color: "inherit", background: "var(--bg-tertiary)" }}
              >
                <img
                  src={r.profile_image || ""}
                  alt=""
                  style={{ width: 32, height: 32, borderRadius: 6, objectFit: "cover", background: "var(--bg-secondary)" }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.9em" }}>{r.display_name || r.username}</div>
                  <div style={{ fontSize: "0.8em", color: "var(--text-muted)" }}>@{r.username}</div>
                </div>
                <span style={{ fontSize: "0.8em", color: "var(--text-muted)" }}>{sourceLabels[r.source] || r.source}</span>
              </Link>
            ))}
          </div>
        )}
        {searchResults !== null && searchResults.length === 0 && !searching && (
          <div style={{ fontSize: "0.85em", color: "var(--text-muted)", marginTop: 4 }}>검색 결과가 없습니다.</div>
        )}
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
