"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

type ExportItem = { key: string; name: string; count: number; format: string };
type ArchiveJob = {
  id: number;
  uuid: string;
  status: "pending" | "processing" | "completed" | "failed";
  size_bytes: number;
  error: string;
  created_at: string | null;
  completed_at: string | null;
  download_url: string;
};

export default function DataPage() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<ExportItem[]>([]);
  const [countsLoading, setCountsLoading] = useState(true);
  const [importResult, setImportResult] = useState<string>("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [archiveJob, setArchiveJob] = useState<ArchiveJob | null>(null);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/settings/export-counts", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setItems(d.items || []))
      .catch(() => setItems([]))
      .finally(() => setCountsLoading(false));
  }, []);

  const loadArchiveStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/settings/archive-status", { credentials: "include" });
      if (!res.ok) return;
      const d = await res.json();
      setArchiveJob(d.job || null);
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/archive-status", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => { if (!cancelled) setArchiveJob(d.job || null); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!archiveJob || (archiveJob.status !== "pending" && archiveJob.status !== "processing")) return;
    const timer = setInterval(loadArchiveStatus, 3000);
    return () => clearInterval(timer);
  }, [archiveJob, loadArchiveStatus]);

  const handleExportData = async (type: string) => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/export-data", { credentials: "include" });
      if (!res.ok) { alert("내보내기 실패"); setLoading(false); return; }
      const json: Record<string, unknown> = await res.json();
      const data = type === "all" ? json : (json[type] ?? []);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `writ_${type}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { alert("오류 발생"); }
    setLoading(false);
  };

  const handleExportCsv = async (key: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/settings/export/${key}`, { credentials: "include" });
      if (!res.ok) { alert("내보내기 실패"); setLoading(false); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `writ_${key}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { alert("오류 발생"); }
    setLoading(false);
  };

  const handleRowExport = (item: ExportItem) => {
    if (item.format === "JSON") {
      handleExportData(item.key === "filters" ? "keyword_mutes" : item.key);
    } else {
      handleExportCsv(item.key);
    }
  };

  const handleRequestArchive = async () => {
    setArchiveLoading(true);
    setArchiveError("");
    try {
      const res = await fetch("/api/settings/archive-request", { method: "POST", credentials: "include" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        setArchiveError(d.detail || "아카이브 요청에 실패했습니다.");
        return;
      }
      setArchiveJob(d.job || null);
    } catch {
      setArchiveError("아카이브 요청 중 오류가 발생했습니다.");
    } finally {
      setArchiveLoading(false);
    }
  };

  const handleDownloadArchive = () => {
    if (!archiveJob?.download_url) return;
    window.location.href = archiveJob.download_url;
  };

  const formatBytes = (bytes: number) => {
    if (!bytes) return "";
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const handleImport = async () => {
    if (!importFile) return;
    setLoading(true);
    setImportResult("");
    try {
      const text = await importFile.text();
      const json = JSON.parse(text);
      const formData = new FormData();
      formData.append("data", JSON.stringify(json));
      const res = await fetch("/api/settings/import-data", { method: "POST", credentials: "include", body: formData });
      const d = await res.json();
      if (!res.ok) { setImportResult(`실패: ${d.detail || "알 수 없는 오류"}`); }
      else {
        const imported = d.imported;
        const parts = [];
        if (imported.follows) parts.push(`팔로우 ${imported.follows}건`);
        if (imported.mutes) parts.push(`뮤트 ${imported.mutes}건`);
        if (imported.blocks) parts.push(`차단 ${imported.blocks}건`);
        if (imported.bookmarks) parts.push(`북마크 ${imported.bookmarks}건`);
        if (imported.keyword_mutes) parts.push(`키워드 뮤트 ${imported.keyword_mutes}건`);
        setImportResult(parts.length ? `가져오기 완료: ${parts.join(", ")}` : "가져올 데이터가 없습니다.");
      }
    } catch { setImportResult("JSON 파일을 확인해 주세요."); }
    setLoading(false);
    setImportFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
      <SettingsNav current="data" />

      <div className="novel-form">
        <h3 style={{ fontSize: "1.05em", marginBottom: 12 }}>내보내기</h3>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 16 }}>
          계정 데이터를 파일로 내려받을 수 있습니다.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 24 }}>
          <button onClick={() => handleExportData("all")} disabled={loading} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
            전체 데이터 내보내기 (팔로우/뮤트/차단/북마크/키워드뮤트)
          </button>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {archiveJob?.status === "completed" ? (
              <>
                <p style={{ fontSize: 14, color: "var(--success)", margin: 0 }}>
                  아카이브가 준비되었습니다{archiveJob.size_bytes ? ` (${formatBytes(archiveJob.size_bytes)})` : ""}.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button onClick={handleDownloadArchive} disabled={loading} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
                    아카이브 다운로드 (ZIP)
                  </button>
                  <button onClick={handleRequestArchive} disabled={archiveLoading} className="btn btn-outline" style={{ alignSelf: "flex-start" }}>
                    새로 만들기
                  </button>
                </div>
                <p className="form-help" style={{ margin: 0 }}>
                  생성 후 7일간 다운로드할 수 있으며, 이후 서버에서 자동 삭제됩니다.
                </p>
              </>
            ) : archiveJob && (archiveJob.status === "pending" || archiveJob.status === "processing") ? (
              <p style={{ fontSize: 14, color: "var(--accent)", margin: 0 }}>
                서버에서 아카이브를 생성하고 있습니다. 완료되면 알림으로 알려드립니다.
              </p>
            ) : (
              <>
                <button onClick={handleRequestArchive} disabled={archiveLoading} className="btn btn-outline" style={{ alignSelf: "flex-start" }}>
                  {archiveLoading ? "요청 중..." : "게시물/시리즈 아카이브 (ZIP)"}
                </button>
                <p className="form-help" style={{ margin: 0 }}>
                  프로필 정보와 사진, 게시물, 시리즈/에피소드를 포함한 ZIP을 서버에서 생성합니다.
                  완료되면 알림으로 알려드리며, 생성 후 7일간 다운로드할 수 있습니다.
                </p>
              </>
            )}
            {archiveJob?.status === "failed" && (
              <p style={{ fontSize: 14, color: "var(--danger)", margin: 0 }}>
                아카이브 생성에 실패했습니다{archiveJob.error ? `: ${archiveJob.error}` : ""}.
              </p>
            )}
            {archiveError && <p style={{ fontSize: 14, color: "var(--danger)", margin: 0 }}>{archiveError}</p>}
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 16 }}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>가져오기/내보내기 형식</p>
          {countsLoading ? (
            <p style={{ fontSize: 13, color: "var(--text-muted)" }}>불러오는 중...</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr className="admin-tr text-muted">
                    <th>데이터</th>
                    <th>개수</th>
                    <th>형식</th>
                    <th style={{ textAlign: "right" }}></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.key}>
                      <td style={{ padding: 10 }}>{it.name}</td>
                      <td style={{ padding: 10 }}>{it.count}</td>
                      <td style={{ padding: 10 }}>{it.format}</td>
                      <td style={{ padding: 10, textAlign: "right" }}>
                        {it.format && (
                          <button onClick={() => handleRowExport(it)} disabled={loading} className="btn btn-small btn-outline">
                            내보내기
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 24 }}>
          <h3 style={{ fontSize: "1.05em", marginBottom: 12 }}>가져오기</h3>
          <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 16 }}>
            JSON 파일에서 팔로우 목록, 뮤트, 차단, 북마크, 키워드 뮤트를 가져옵니다.
          </p>

          <div className="form-group" style={{ marginBottom: 12 }}>
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              onChange={(e) => setImportFile(e.target.files?.[0] || null)}
              style={{ fontSize: 14 }}
            />
          </div>
          <button onClick={handleImport} disabled={loading || !importFile} className="btn btn-primary">
            {loading ? "가져오는 중..." : "가져오기"}
          </button>
          {importResult && (
            <p style={{ marginTop: 8, fontSize: 14, color: importResult.includes("실패") || importResult.includes("확인") ? "var(--danger)" : "var(--success)" }}>
              {importResult}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
