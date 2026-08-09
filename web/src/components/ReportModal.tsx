"use client";
import { useEffect, useState } from "react";
import { PostData } from "@/lib/api";

export default function ReportModal({ post, onClose }: { post: PostData; onClose: () => void }) {
  const [reportReason, setReportReason] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(false);
  const [reportForward, setReportForward] = useState(false);
  const [reportRules, setReportRules] = useState<{ id: number; title: string; description: string }[]>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<number[]>([]);

  useEffect(() => {
    fetch("/api/rules").then(r => r.json()).then(setReportRules).catch(() => {});
  }, []);

  const handleReport = async () => {
    if (selectedRuleIds.length === 0 && reportReason.trim().length < 10) { setReportError("규칙을 선택하거나 사유를 10자 이상 입력해주세요."); return; }
    setReportError("");
    try {
      const form = new FormData();
      form.append("target_type", "post");
      form.append("target_id", String(post.id));
      form.append("reason", reportReason.trim());
      form.append("forward_to_remote", reportForward ? "true" : "");
      form.append("rule_ids", JSON.stringify(selectedRuleIds));
      const res = await fetch("/api/reports", { method: "POST", credentials: "include", body: form });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "신고 실패"); }
      setReportDone(true);
    } catch (e) {
      setReportError(e instanceof Error ? e.message : "신고 처리 중 오류가 발생했습니다.");
    }
  };

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <button className="reply-modal-close" onClick={onClose}>×</button>
        <h3>게시글 신고</h3>
        {reportDone ? (
          <p style={{ color: "var(--text-secondary)", margin: "16px 0" }}>신고가 접수되었습니다. 검토 후 조치하겠습니다.</p>
        ) : (
          <>
            {reportRules.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--text-secondary)" }}>위반 규칙</p>
                {reportRules.map((rule) => (
                  <label key={rule.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 4, borderRadius: 6, border: selectedRuleIds.includes(rule.id) ? "1px solid var(--accent)" : "1px solid var(--border)", background: selectedRuleIds.includes(rule.id) ? "var(--bg-tertiary)" : "var(--bg-secondary)", cursor: "pointer", transition: "all 0.15s" }}>
                    <input type="checkbox" checked={selectedRuleIds.includes(rule.id)} onChange={(e) => setSelectedRuleIds((prev) => e.target.checked ? [...prev, rule.id] : prev.filter((id) => id !== rule.id))} style={{ marginTop: 2, accentColor: "var(--accent)" }} />
                    <span style={{ fontSize: 13, color: "var(--text)" }}><strong>{rule.title}</strong>{rule.description ? <span style={{ color: "var(--text-secondary)" }}>{` — ${rule.description}`}</span> : ""}</span>
                  </label>
                ))}
              </div>
            )}
            <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: "var(--text-secondary)" }}>기타 사유</p>
            <textarea
              value={reportReason}
              onChange={(e) => setReportReason(e.target.value)}
              placeholder={selectedRuleIds.length > 0 ? "추가 사유 (선택)" : "신고 사유를 입력해주세요 (최소 10자)"}
              style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
            />
            {reportError && <p style={{ color: "var(--error)", fontSize: 14, marginBottom: 8 }}>{reportError}</p>}
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 8, color: "var(--text-secondary)", cursor: "pointer" }}>
              <input type="checkbox" checked={reportForward} onChange={(e) => setReportForward(e.target.checked)} />
              원격 서버로 신고 전송
            </label>
            <button onClick={handleReport} className="btn" style={{ width: "100%" }}>신고 제출</button>
          </>
        )}
      </div>
    </div>
  );
}
