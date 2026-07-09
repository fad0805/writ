"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData, NotificationData } from "@/lib/api";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function MigratePage() {
  const router = useRouter();
  const [aliasInput, setAliasInput] = useState("");
  const [aliases, setAliases] = useState<string[]>([]);
  const [pendingRequests, setPendingRequests] = useState<NotificationData[]>([]);
  const [mySeries, setMySeries] = useState<NovelData[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<number[]>([]);
  const [targetUsername, setTargetUsername] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [aliasesRes, notifs, novels] = await Promise.all([
        fetch("/api/settings/aliases", { credentials: "include" }).then(r => r.json()),
        api.getNotifications("moderation"),
        api.getMyNovels(999, 0),
      ]);
      setAliases(aliasesRes.aliases || []);
      setPendingRequests(notifs.notifications.filter((n: any) => n.metadata?.type === "migrate_request"));
      setMySeries(novels.novels);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAddAlias = useCallback(async () => {
    const val = aliasInput.trim();
    if (!val || !val.includes("@")) return;
    if (aliases.includes(val)) { setError("이미 등록된 별칭입니다."); return; }
    const newAliases = [...aliases, val];
    setSubmitting(true); setError("");
    try {
      const form = new FormData();
      form.append("aliases", JSON.stringify(newAliases));
      const res = await fetch("/api/settings/aliases", { method: "POST", credentials: "include", body: form });
      if (res.ok) { setAliases(newAliases); setAliasInput(""); setMsg("별칭이 등록되었습니다."); }
      else { const d = await res.json(); setError(d.detail || "등록 실패"); }
    } catch { setError("오류 발생"); }
    setSubmitting(false);
  }, [aliasInput, aliases]);

  const handleRemoveAlias = useCallback(async (alias: string) => {
    const newAliases = aliases.filter((a) => a !== alias);
    const form = new FormData();
    form.append("aliases", JSON.stringify(newAliases));
    await fetch("/api/settings/aliases", { method: "POST", credentials: "include", body: form });
    setAliases(newAliases);
  }, [aliases]);

  const handleMigrate = useCallback(async () => {
    if (!targetUsername.trim()) { setError("이전할 계정의 사용자 이름을 입력하세요."); return; }
    if (!confirm(`정말 ${targetUsername}(으)로 계정을 이전하시겠습니까?\n\n이전 후 현재 계정은 동결됩니다.`)) return;
    setSubmitting(true); setMsg(""); setError("");
    try {
      const form = new FormData();
      form.append("target_username", targetUsername.trim());
      form.append("series_ids", JSON.stringify(selectedSeries));
      const res = await fetch("/api/settings/migrate", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        const d = await res.json();
        setMsg(d.message || "이전 요청을 보냈습니다.");
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

      <div className="novel-form" style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: "1.05em", marginBottom: 8 }}>계정 별칭</h3>
        <p className="form-help" style={{ marginBottom: 12 }}>
          다른 계정에서 이 계정으로 옮겨오려면, 이전 계정의 핸들을 별칭으로 등록하세요.
          팔로워를 이쪽으로 옮기는 데 필요합니다. 별칭 등록 자체는 되돌릴 수 있습니다.
        </p>

        {aliases.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            {aliases.map((a) => (
              <div key={a} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
                <span style={{ fontSize: 14 }}>@{a}</span>
                <button onClick={() => handleRemoveAlias(a)} className="btn btn-small btn-outline" style={{ color: "var(--danger)", padding: "2px 8px", fontSize: 12 }}>제거</button>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="text" value={aliasInput} onChange={(e) => setAliasInput(e.target.value)} placeholder="@user@domain" style={{ flex: 1 }} />
          <button onClick={handleAddAlias} disabled={submitting || !aliasInput.trim()} className="btn btn-primary btn-small">등록</button>
        </div>
      </div>

      {pendingRequests.length > 0 && (
        <div className="novel-form" style={{ marginBottom: 24 }}>
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
        <h3 style={{ fontSize: "1.05em", marginBottom: 8 }}>계정 이전</h3>
        <p className="form-help" style={{ marginBottom: 12 }}>
          계정 이전은 이전 계정에서 시작합니다. 먼저 새 계정에 이전 계정의 별칭을 등록한 후,
          이전 계정에서 아래 폼을 사용해 이전을 요청하세요.
        </p>
        <div className="form-group">
          <label>이전 계정의 핸들</label>
          <input type="text" value={targetUsername} onChange={(e) => setTargetUsername(e.target.value)} placeholder="user@domain" />
          <p className="form-help">이동하고자 하는 계정의 사용자이름@도메인을 설정하세요. 같은 서버라면 사용자이름만 입력.</p>
        </div>

        {mySeries.length > 0 && (
          <div className="form-group">
            <label>함께 가져갈 시리즈 (같은 서버만 가능)</label>
            <p className="form-help" style={{ marginBottom: 8 }}>같은 서버 내 계정으로만 시리즈 이전이 가능합니다.</p>
            <p style={{ color: "var(--danger)", fontSize: 13, marginBottom: 8 }}>⚠ 시리즈 이전은 되돌릴 수 없습니다. 신중히 선택해주세요.</p>
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
