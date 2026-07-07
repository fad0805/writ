"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";
import Link from "next/link";

interface TargetInfo {
  id: number;
  content?: string;
  title?: string;
  description?: string;
  novel_id?: number;
  novel_title?: string;
  author: { id: number; username: string; display_name: string };
  author_id: number;
  is_deleted?: boolean;
}

interface ReportDetail {
  id: number;
  reporter: { id: number; username: string; display_name: string };
  target_type: string;
  target_id: number;
  reason: string;
  status: string;
  created_at: string | null;
  target?: TargetInfo;
  resolved_by?: { id: number; username: string };
}

const targetTypeNames: Record<string, string> = { post: "게시글", novel: "시리즈", episode: "에피소드" };

export default function ReportDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");

  // Moderation modal
  const [showModerate, setShowModerate] = useState(false);
  const [modAction, setModAction] = useState("warning");
  const [modMessage, setModMessage] = useState("");
  const [modEmail, setModEmail] = useState(false);



  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/reports/${params.id}`, { credentials: "include" });
      if (res.ok) {
        const r = await res.json();
        setReport(r);
      } else {
        setMsg("신고를 불러올 수 없습니다.");
      }
    } catch { setMsg("오류 발생"); }
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => { if (!authLoading) load(); }, [params.id, authLoading]);

  const handleAction = async (action: "resolve" | "dismiss") => {
    setMsg("");
    try {
      const res = await fetch(`/api/admin/reports/${params.id}/${action}`, { method: "POST", credentials: "include" });
      if (res.ok) { setMsg(action === "resolve" ? "처리 완료되었습니다." : "기각되었습니다."); load(); }
      else { setMsg("처리 실패"); }
    } catch { setMsg("오류 발생"); }
  };

  const handleModerate = async () => {
    const form = new FormData();
    form.append("action", modAction);
    form.append("message", modMessage);
    if (modEmail) form.append("send_email", "true");
    const targetAuthorId = report?.target?.author_id;
    if (!targetAuthorId) return;
    try {
      const res = await fetch(`/api/admin/users/${targetAuthorId}/moderate`, { method: "POST", credentials: "include", body: form });
      if (res.ok) { setShowModerate(false); setMsg("조치가 적용되었습니다."); load(); }
      else { alert("실패"); }
    } catch { alert("오류"); }
  };

  const handleSetCw = async () => {
    const form = new FormData();
    form.append("summary", "");
    try {
      const res = await fetch(`/api/admin/posts/${report!.target_id}/set-cw`, { method: "POST", credentials: "include", body: form });
      if (res.ok) { setMsg("CW가 설정되었습니다."); load(); }
      else { alert("실패"); }
    } catch { alert("오류"); }
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;
  if (!report) return <div className="empty-state">신고를 찾을 수 없습니다.</div>;

  const target = report.target;
  const targetUrl = report.target_type === "post"
    ? `/post/${report.target_id}`
    : report.target_type === "novel"
    ? `/series/${report.target_id}`
    : target?.novel_id ? `/series/${target.novel_id}/episodes/${report.target_id}` : "#";

  return (
    <>
      <div className="page-header" style={{ justifyContent: "space-between" }}>
        <h2><Icon name="flag" /> 신고 상세</h2>
        <Link href="/admin/reports" className="btn btn-small btn-outline">목록</Link>
      </div>
      <AdminNav current="reports" />

      {msg && <p style={{ color: "var(--text-secondary)", marginBottom: 12, fontSize: 14 }}>{msg}</p>}

      <div className="card" style={{ padding: 20, maxWidth: 720 }}>
        {/* Status badge */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <span className={`badge ${report.status === "pending" ? "badge-warning" : report.status === "resolved" ? "badge-ok" : "badge-muted"}`}>
            {report.status === "pending" ? "대기중" : report.status === "resolved" ? "처리완료" : "기각"}
          </span>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {report.created_at ? new Date(report.created_at).toLocaleString("ko-KR") : ""}
          </span>
        </div>

        {/* Reporter */}
        <div className="report-section">
          <div className="report-label">신고자</div>
          <Link href={`/@${report.reporter.username}`} className="mention-link" style={{ fontWeight: 600 }}>
            {report.reporter.display_name || report.reporter.username}
          </Link>
          <span style={{ color: "var(--text-muted)", fontSize: 13, marginLeft: 8 }}>@{report.reporter.username}</span>
        </div>

        {/* Target */}
        <div className="report-section">
          <div className="report-label">신고 대상</div>
          <div style={{ marginBottom: 4 }}>
            <span className="vis-badge" style={{ background: "var(--bg-tertiary)", padding: "2px 8px", borderRadius: 4, fontSize: 12 }}>
              {targetTypeNames[report.target_type] || report.target_type}
            </span>
            <span style={{ marginLeft: 8, color: "var(--text-muted)", fontSize: 13 }}>#{report.target_id}</span>
          </div>
          {target && (
            <div style={{ marginTop: 8, padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
              {target.title && <div style={{ fontWeight: 600, marginBottom: 4 }}>{target.title}</div>}
              {target.content && (
                <div style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 4, whiteSpace: "pre-wrap", maxHeight: 120, overflow: "auto" }}>
                  {target.content.length > 300 ? target.content.slice(0, 300) + "..." : target.content}
                </div>
              )}
              {target.description && (
                <div style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 4 }}>{target.description}</div>
              )}
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>
                작성자: <Link href={`/admin/users/${target.author_id}`} className="mention-link">{target.author.display_name || target.author.username}</Link>
                {target.novel_title && <span> · {target.novel_title}</span>}
                {target.is_deleted && <span> · <span style={{ color: "var(--danger)" }}>삭제됨</span></span>}
              </div>
              <Link href={targetUrl} className="mention-link" style={{ fontSize: 13, display: "inline-block", marginTop: 6 }}>대상 보기 →</Link>
            </div>
          )}
        </div>

        {/* Reason */}
        <div className="report-section">
          <div className="report-label">신고 사유</div>
          <div style={{ fontSize: 14, whiteSpace: "pre-wrap", background: "var(--bg-tertiary)", padding: 12, borderRadius: 8, lineHeight: 1.6 }}>{report.reason}</div>
        </div>

        {/* Resolver */}
        {report.resolved_by && (
          <div className="report-section">
            <div className="report-label">처리자</div>
            <span>{report.resolved_by.username}</span>
          </div>
        )}

        {/* Actions */}
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 8 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {report.status === "pending" && (
              <>
                <button className="btn btn-primary" onClick={() => handleAction("resolve")}>
                  <Icon name="check" /> 처리 완료
                </button>
                <button className="btn btn-outline" onClick={() => handleAction("dismiss")} style={{ color: "var(--text-muted)" }}>
                  <Icon name="x" /> 기각
                </button>
              </>
            )}
            {report.target?.author_id && (
              <button className="btn btn-outline" style={{ color: "var(--danger)" }} onClick={() => { setShowModerate(true); setModAction("warning"); setModMessage(""); }}>
                <Icon name="shield" /> 작성자 중재
              </button>
            )}
            {report.target_type === "post" && target?.content !== undefined && (
              <button className="btn btn-outline" onClick={handleSetCw}>
                <Icon name="eye" /> CW 설정
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Moderation modal */}
      {showModerate && target?.author_id && (
        <div className="reply-modal-backdrop active" onClick={() => setShowModerate(false)}>
          <div className="reply-modal mod-modal" onClick={(e) => e.stopPropagation()}>
            <button className="reply-modal-close" onClick={() => setShowModerate(false)}>×</button>
            <h3>작성자 중재</h3>
            <div className="mod-form">
              <div>
                <label className="admin-section-label">대상</label>
                <div style={{ fontSize: 14, marginBottom: 8 }}>
                  <Link href={`/admin/users/${target.author_id}`} className="mention-link">{target.author.display_name || target.author.username}</Link>
                  <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>@{target.author.username}</span>
                </div>
              </div>
              <div>
                <label className="admin-section-label">조치</label>
                <select value={modAction} onChange={e => setModAction(e.target.value)} className="cw-input mod-select">
                  <option value="warning">경고</option>
                  <option value="freeze">동결</option>
                  <option value="sensitive">민감함</option>
                  <option value="limit">제한</option>
                  <option value="suspend">정지</option>
                </select>
              </div>
              <div>
                <label className="admin-section-label">메세지</label>
                <textarea value={modMessage} onChange={e => setModMessage(e.target.value)} rows={4} className="cw-input mod-textarea" placeholder="사용자에게 보낼 메세지..." />
              </div>
              <div>
                <label className="text-sm text-muted flex-center" style={{ gap: 6, cursor: "pointer" }}>
                  <input type="checkbox" checked={modEmail} onChange={e => setModEmail(e.target.checked)} />
                  이메일로 알림 보내기
                </label>
              </div>
              <div className="form-actions">
                <button onClick={handleModerate} className="btn btn-primary">적용</button>
                <button onClick={() => setShowModerate(false)} className="btn btn-outline">취소</button>
              </div>
            </div>
          </div>
        </div>
      )}

    </>
  );
}
