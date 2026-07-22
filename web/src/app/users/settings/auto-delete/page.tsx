"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";

export default function AutoDeleteSettingsPage() {
  const router = useRouter();
  const [postLifetime, setPostLifetime] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => r.json())
      .then((u) => { setPostLifetime(u.post_lifetime || 0); setLoading(false); })
      .catch(() => router.push("/login"));
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("post_lifetime", String(postLifetime));
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
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">설정 저장</button>
        </div>
      </form>
    </>
  );
}
