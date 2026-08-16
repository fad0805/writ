"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

const EXCEPTIONS = [
  { key: "pinned", label: "고정된 게시물", icon: "pin" },
  { key: "dm", label: "다이렉트 메시지", icon: "direct" },
  { key: "liked", label: "내가 좋아요한 게시물", icon: "star_filled" },
  { key: "bookmarked", label: "내가 북마크한 게시물", icon: "bookmark" },
  { key: "poll", label: "설문이 있는 게시물", icon: "chart" },
  { key: "media", label: "미디어가 있는 게시물", icon: "image" },
];

export default function AutoDeleteSettingsPage() {
  const router = useRouter();
  const [postLifetime, setPostLifetime] = useState(0);
  const [exceptions, setExceptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => r.json())
      .then((u) => {
        setPostLifetime(u.post_lifetime || 0);
        setExceptions(u.post_lifetime_exceptions || []);
        setLoading(false);
      })
      .catch(() => router.push("/login"));
  }, [router]);

  const toggleException = (key: string) => {
    setExceptions((prev) => prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("post_lifetime", String(postLifetime));
      form.append("post_lifetime_exceptions", JSON.stringify(exceptions));
      const res = await fetch("/api/settings/update", {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (res.ok) alert("저장되었습니다");
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="trash" /> 자동 삭제</h2>
      </div>
      <SettingsNav current="auto-delete" />
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>포스트 자동 삭제 기간</label>
          <select value={postLifetime} onChange={(e) => setPostLifetime(Number(e.target.value))} style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg-secondary)", color: "var(--text-primary)", fontSize: 14, width: "100%" }}>
            <option value={0}>사용 안 함</option>
            <option value={7}>1주</option>
            <option value={14}>2주</option>
            <option value={30}>1개월</option>
            <option value={60}>2개월</option>
            <option value={90}>3개월</option>
            <option value={180}>6개월</option>
            <option value={365}>1년</option>
            <option value={730}>2년</option>
          </select>
          <p className="form-help" style={{ marginTop: 8, color: "var(--text-secondary)" }}>
            설정한 기간이 지난 모든 게시물이 자동으로 삭제됩니다. 변경 즉시 반영되며, 기존 글도 새 설정 기준으로 적용됩니다.
          </p>
          <p className="form-help" style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>
            자동 삭제 작업은 서버가 한가한 새벽 시간에 백그라운드에서 돌아가기 때문에, 설정 후 바로 삭제되지 않을 수 있습니다.
          </p>
        </div>

        <div className="form-group">
          <label>삭제 예외</label>
          <p className="form-help" style={{ marginBottom: 8, color: "var(--text-secondary)" }}>
            선택한 항목에 해당하는 게시물은 자동 삭제에서 제외됩니다.
          </p>
          {postLifetime === 0 && (
            <p className="form-help" style={{ marginBottom: 8, color: "var(--text-muted)", fontSize: "0.85em" }}>
              자동 삭제가 꺼져 있어도 예외 설정은 저장됩니다. 기간을 선택하면 바로 적용됩니다.
            </p>
          )}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {EXCEPTIONS.map((ex) => (
                <label key={ex.key} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", padding: "6px 10px", borderRadius: 6, background: exceptions.includes(ex.key) ? "color-mix(in srgb, var(--accent) 10%, transparent)" : "var(--bg-tertiary)", border: `1px solid ${exceptions.includes(ex.key) ? "var(--accent)" : "var(--border)"}`, transition: "all 0.15s" }}>
                  <input type="checkbox" checked={exceptions.includes(ex.key)} onChange={() => toggleException(ex.key)} style={{ accentColor: "var(--accent)" }} />
                  <Icon name={ex.icon} size={14} />
                  <span style={{ fontSize: 14 }}>{ex.label}</span>
                </label>
              ))}
            </div>
        </div>

        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">설정 저장</button>
        </div>
      </form>
    </>
  );
}
