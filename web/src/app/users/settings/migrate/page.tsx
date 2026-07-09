"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData, NotificationData } from "@/lib/api";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function MigratePage() {
  const router = useRouter();
  const [targetUsername, setTargetUsername] = useState("");
  const [mySeries, setMySeries] = useState<NovelData[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<number[]>([]);
  const [pendingRequests, setPendingRequests] = useState<NotificationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getMyNovels(999, 0),
      api.getNotifications("moderation"),
    ]).then(([novels, notifs]) => {
      setMySeries(novels.novels);
      setPendingRequests(notifs.notifications.filter((n: any) => n.metadata?.type === "migrate_request"));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const handleMigrate = useCallback(async () => {
    if (!targetUsername.trim()) { setError("이전할 계정의 사용자 이름을 입력하세요."); return; }
    if (!confirm("정말 이전 요청을 보내시겠습니까?\n\n이전 후 현재 계정은 동결되며, 상대방이 수락해야 완료됩니다.")) return;
    setSubmitting(true); setMsg(""); setError("");
    try {
      const form = new FormData();
      form.append("target_username", targetUsername.trim());
      form.append("series_ids", JSON.stringify(selectedSeries));
      const res = await fetch("/api/settings/migrate", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        setMsg("이전 요청을 보냈습니다. 상대방이 수락하면 이전이 완료됩니다.");
      } else {
        const d = await res.json().catch(() => ({}));
        setError(d.detail || "요청 실패");
      }
    } catch { setError("오류 발생"); }
    setSubmitting(false);
  }, [targetUsername, selectedSeries]);

  const handleApprove = useCallback(async (n: NotificationData) => {
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("notification_id", String(n.id));
      const res = await fetch("/api/settings/migrate/approve", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        setMsg("계정 이전을 수락했습니다.");
        setPendingRequests((prev) => prev.filter((x) => x.id !== n.id));
      } else {
        const d = await res.json().catch(() => ({}));
        setError(d.detail || "수락 실패");
      }
    } catch { setError("오류 발생"); }
    setSubmitting(false);
  }, []);

  if (loading) return <><SettingsNav current="migrate" /><p className="empty-state">로딩 중...</p></>;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
      <SettingsNav current="migrate" />
      {msg && <p style={{ color: "var(--accent)", fontWeight: 600, marginBottom: 12 }}>{msg}</p>}

      {pendingRequests.length > 0 && (
        <div className="novel-form" style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: "1.05em", marginBottom: 12 }}>받은 이전 요청</h3>
          {pendingRequests.map((n) => (
            <div key={n.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 8, marginBottom: 6 }}>
              <div style={{ flex: 1, fontSize: 14 }}>
                <strong>{n.from_user?.display_name || n.from_user?.username}</strong>
                <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>@{n.from_user?.username}</span>
                <span style={{ marginLeft: 8, color: "var(--text-secondary)" }}>님이 계정 이전을 요청했습니다</span>
              </div>
              <button onClick={() => handleApprove(n)} disabled={submitting} className="btn btn-primary btn-small">수락</button>
            </div>
          ))}
        </div>
      )}

      <div className="novel-form">
        <div className="form-group">
          <label>이전할 계정</label>
          <input type="text" value={targetUsername} onChange={(e) => setTargetUsername(e.target.value)} placeholder="동일 서버의 사용자 이름" />
          <p className="form-help">같은 서버 내 계정으로만 이전 가능합니다. 요청을 보내면 상대방이 수락해야 완료됩니다.</p>
        </div>

        {mySeries.length > 0 && (
          <div className="form-group">
            <label>함께 보낼 시리즈 (선택)</label>
            <p className="form-help" style={{ marginBottom: 8 }}>선택한 시리즈의 소유자가 이전됩니다.</p>
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
          <button onClick={handleMigrate} disabled={submitting} className="btn btn-danger">{submitting ? "처리 중..." : "이전 요청 보내기"}</button>
        </div>
      </div>
    </>
  );
}
