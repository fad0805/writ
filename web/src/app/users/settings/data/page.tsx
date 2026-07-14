"use client";
import { useState, useRef } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function DataPage() {
  const [loading, setLoading] = useState(false);
  const [importResult, setImportResult] = useState<string>("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleExportData = async (type: string) => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/export-data", { credentials: "include" });
      if (!res.ok) { alert("내보내기 실패"); setLoading(false); return; }
      const json = await res.json();
      let data: any;
      if (type === "all") {
        data = json;
      } else {
        data = json[type] || [];
      }
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

  const handleExportArchive = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/export-archive", { credentials: "include" });
      if (!res.ok) { alert("아카이브 내보내기 실패"); setLoading(false); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "writ_archive.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch { alert("오류 발생"); }
    setLoading(false);
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
          계정 데이터를 JSON 파일로 내려받을 수 있습니다.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 24 }}>
          <button onClick={() => handleExportData("all")} disabled={loading} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
            전체 데이터 내보내기 (팔로우/뮤트/차단/북마크/키워드뮤트)
          </button>
          <button onClick={handleExportArchive} disabled={loading} className="btn btn-outline" style={{ alignSelf: "flex-start" }}>
            게시물/시리즈 아카이브 (ZIP)
          </button>
        </div>

        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 16 }}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>개별 내보내기</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={() => handleExportData("follows")} disabled={loading} className="btn btn-small btn-outline">팔로우</button>
            <button onClick={() => handleExportData("mutes")} disabled={loading} className="btn btn-small btn-outline">뮤트</button>
            <button onClick={() => handleExportData("blocks")} disabled={loading} className="btn btn-small btn-outline">차단</button>
            <button onClick={() => handleExportData("bookmarks")} disabled={loading} className="btn btn-small btn-outline">북마크</button>
            <button onClick={() => handleExportData("keyword_mutes")} disabled={loading} className="btn btn-small btn-outline">키워드 뮤트</button>
          </div>
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
