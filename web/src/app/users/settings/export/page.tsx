"use client";
import { useState, useCallback, useEffect } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

type ArchiveJob = {
  uuid: string;
  status: "pending" | "processing" | "completed" | "failed";
  size_bytes: number;
  error: string;
  download_url: string;
};

export default function ExportPage() {
  const [loading, setLoading] = useState(false);
  const [archiveJob, setArchiveJob] = useState<ArchiveJob | null>(null);
  const [archiveNextAvailableAt, setArchiveNextAvailableAt] = useState<string | null>(null);
  const [archiveError, setArchiveError] = useState("");

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

  const loadArchiveStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/settings/archive-status", { credentials: "include" });
      if (!res.ok) return;
      const d = await res.json();
      setArchiveJob(d.job || null);
      setArchiveNextAvailableAt(d.next_available_at || null);
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/archive-status", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        if (cancelled) return;
        setArchiveJob(d.job || null);
        setArchiveNextAvailableAt(d.next_available_at || null);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!archiveJob || (archiveJob.status !== "pending" && archiveJob.status !== "processing")) return;
    const timer = setInterval(loadArchiveStatus, 3000);
    return () => clearInterval(timer);
  }, [archiveJob, loadArchiveStatus]);

  const formatAvailableAt = (value: string) => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("ko-KR", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  const handleRequestArchive = useCallback(async () => {
    setLoading(true);
    setArchiveError("");
    try {
      const res = await fetch("/api/settings/archive-request", { method: "POST", credentials: "include" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        setArchiveError(d.detail || "요청 실패");
        return;
      }
      setArchiveJob(d.job || null);
    } catch { setArchiveError("오류 발생"); }
    finally { setLoading(false); }
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
          <p className="form-help" style={{ marginBottom: 8 }}>
            프로필 정보와 사진, 모든 게시글, 시리즈/에피소드, 업로드한 미디어를 하나의 ZIP으로 서버에서 생성합니다.
            준비되면 알림을 보내드리며, 생성 후 7일간 다운로드할 수 있습니다. 아카이브는 일주일에 한 번만 만들 수 있습니다.
          </p>
          {archiveJob?.status === "completed" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <p style={{ color: "var(--success)", fontSize: 14, margin: 0 }}>아카이브가 준비되었습니다.</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <a href={archiveJob.download_url} className="btn btn-primary" download>아카이브 다운로드 (ZIP)</a>
                {!archiveNextAvailableAt && (
                  <button onClick={handleRequestArchive} disabled={loading} className="btn btn-outline">새로 만들기</button>
                )}
              </div>
              {archiveNextAvailableAt && (
                <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: 0 }}>
                  다음 아카이브는 {formatAvailableAt(archiveNextAvailableAt)}부터 만들 수 있습니다.
                </p>
              )}
            </div>
          ) : archiveJob && (archiveJob.status === "pending" || archiveJob.status === "processing") ? (
            <p style={{ color: "var(--accent)", fontSize: 14 }}>
              서버에서 아카이브를 생성하고 있습니다. 완료되면 알림으로 알려드립니다.
            </p>
          ) : (
            <button onClick={handleRequestArchive} disabled={loading} className="btn btn-outline">
              {loading ? "요청 중..." : "아카이브 요청"}
            </button>
          )}
          {archiveJob?.status === "failed" && (
            <p style={{ color: "var(--danger)", fontSize: 14 }}>
              아카이브 생성에 실패했습니다{archiveJob.error ? `: ${archiveJob.error}` : ""}.
            </p>
          )}
          {archiveError && <p style={{ color: "var(--danger)", fontSize: 14 }}>{archiveError}</p>}
        </div>
      </div>
    </>
  );
}
