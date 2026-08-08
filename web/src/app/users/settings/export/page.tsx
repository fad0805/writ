"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function ExportPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [archiveRequested, setArchiveRequested] = useState(false);

  const handleDownload = useCallback(async (type: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/settings/export?type=${type}`, { credentials: "include" });
      if (!res.ok) { alert("다운로드 실패"); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${type}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { alert("오류 발생"); }
    setLoading(false);
  }, []);

  const handleRequestArchive = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/archive-request", { method: "POST", credentials: "include" });
      if (res.ok) { setArchiveRequested(true); }
      else { const d = await res.json(); alert(d.detail || "요청 실패"); }
    } catch { alert("오류 발생"); }
    setLoading(false);
  }, []);

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
      <SettingsNav current="data" />

      <div className="novel-form">
        <h3 style={{ fontSize: "1.05em", marginBottom: 12 }}>데이터 내려받기</h3>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 16 }}>
          계정 데이터를 CSV 파일로 내려받을 수 있습니다.
        </p>

        <div className="form-group">
          <label>팔로우 / 리스트 / 뮤트 / 차단 / 북마크 / 필터</label>
          <p className="form-help" style={{ marginBottom: 8 }}>팔로우 목록, 뮤트, 차단, 북마크, 키워드 필터 등의 정보를 한 번에 내려받습니다.</p>
          <button onClick={() => handleDownload("relationships")} disabled={loading} className="btn btn-primary">다운로드</button>
        </div>

        <div className="form-group">
          <label>게시물 및 업로드된 미디어</label>
          <p className="form-help" style={{ marginBottom: 8 }}>모든 게시글과 업로드한 미디어 파일을 아카이브로 요청합니다. 준비되면 알림을 보내드립니다.</p>
          {archiveRequested ? (
            <p style={{ color: "var(--accent)", fontSize: 14 }}>아카이브 요청이 접수되었습니다. 준비되면 알림을 통해 알려드리겠습니다.</p>
          ) : (
            <button onClick={handleRequestArchive} disabled={loading} className="btn btn-outline">아카이브 요청</button>
          )}
        </div>
      </div>
    </>
  );
}
