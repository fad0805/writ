"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function MigratePage() {
  const router = useRouter();
  const [targetUsername, setTargetUsername] = useState("");
  const [mySeries, setMySeries] = useState<NovelData[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.getMyNovels(999, 0).then((d) => { setMySeries(d.novels); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const handleMigrate = useCallback(async () => {
    if (!targetUsername.trim()) { setError("이전할 계정의 사용자 이름을 입력하세요."); return; }
    if (!confirm("정말 계정을 이전하시겠습니까?\n\n이전 후 현재 계정은 동결되며, 로그인이 불가능합니다.\n복구하려면 관리자에게 문의하세요.")) return;
    setSubmitting(true); setMsg(""); setError("");
    try {
      const form = new FormData();
      form.append("target_username", targetUsername.trim());
      form.append("series_ids", JSON.stringify(selectedSeries));
      const res = await fetch("/api/settings/migrate", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        setMsg("계정 이전이 완료되었습니다. 새 계정으로 로그인해주세요.");
      } else {
        const d = await res.json().catch(() => ({}));
        setError(d.detail || "이전 실패");
      }
    } catch { setError("오류 발생"); }
    setSubmitting(false);
  }, [targetUsername, selectedSeries]);

  if (loading) return <><SettingsNav current="migrate" /><p className="empty-state">로딩 중...</p></>;

  return (
    <>
      <div className="page-header"><h2><Icon name="direct" /> 계정 이전</h2></div>
      <SettingsNav current="migrate" />
      {msg && <p style={{ color: "var(--accent)", fontWeight: 600, marginBottom: 12 }}>{msg}</p>}

      <div className="novel-form">
        <div className="form-group">
          <label>이전할 계정</label>
          <input type="text" value={targetUsername} onChange={(e) => setTargetUsername(e.target.value)} placeholder="동일 서버의 사용자 이름" />
          <p className="form-help">같은 서버 내 계정으로만 이전 가능합니다. 이전 후 현재 계정은 동결됩니다.</p>
        </div>

        {mySeries.length > 0 && (
          <div className="form-group">
            <label>함께 가져갈 시리즈 (선택)</label>
            <p className="form-help" style={{ marginBottom: 8 }}>선택한 시리즈의 소유자가 새 계정으로 변경됩니다.</p>
            {mySeries.map((n) => (
              <label key={n.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", cursor: "pointer", fontSize: 14 }}>
                <input type="checkbox" checked={selectedSeries.includes(n.id)} onChange={(e) => setSelectedSeries((prev) => e.target.checked ? [...prev, n.id] : prev.filter((id) => id !== n.id))} />
                <span>{n.title}</span>
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>({n.episode_count}화)</span>
              </label>
            ))}
          </div>
        )}

        {error && <p style={{ color: "var(--danger)", marginBottom: 12 }}>{error}</p>}
        <div className="form-actions">
          <button onClick={handleMigrate} disabled={submitting} className="btn btn-danger">{submitting ? "처리 중..." : "계정 이전"}</button>
        </div>
      </div>
    </>
  );
}
