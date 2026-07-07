"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

interface Report {
  id: number;
  reporter: { id: number; username: string; display_name: string };
  target_type: string;
  target_id: number;
  reason: string;
  status: string;
  created_at: string | null;
  target?: any;
  resolved_by?: { id: number; username: string };
}

export default function AdminReportsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [reports, setReports] = useState<Report[]>([]);
  const [total, setTotal] = useState(0);
  const [filterStatus, setFilterStatus] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState("");

  const loadReports = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/reports?status=${filterStatus}`, { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        setReports(data.reports);
        setTotal(data.total);
      }
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => { loadReports(); }, [filterStatus]);

  const handleAction = async (reportId: number, action: "resolve" | "dismiss") => {
    setActionMsg("");
    try {
      const res = await fetch(`/api/admin/reports/${reportId}/${action}`, { method: "POST", credentials: "include" });
      if (res.ok) {
        setReports((prev) => prev.map((r) => r.id === reportId ? { ...r, status: action === "resolve" ? "resolved" : "dismissed" } : r));
      } else {
        setActionMsg("처리 실패");
      }
    } catch {
      setActionMsg("오류 발생");
    }
  };

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="flag" /> 신고 관리</h2>
      </div>
      <AdminNav current="reports" />
      <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
        {["pending", "resolved", "dismissed"].map((s) => (
          <button key={s} className={`btn btn-small ${filterStatus === s ? "btn-primary" : "btn-outline"}`} onClick={() => setFilterStatus(s)}>
            {s === "pending" ? "대기중" : s === "resolved" ? "처리됨" : "기각됨"} {s === filterStatus && `(${total})`}
          </button>
        ))}
      </div>
      {actionMsg && <p style={{ color: "var(--error)", marginBottom: 8 }}>{actionMsg}</p>}
      {loading ? (
        <p className="empty-state">로딩 중...</p>
      ) : reports.length === 0 ? (
        <p className="empty-state">신고가 없습니다.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {reports.map((r) => (
            <div key={r.id} className="report-card" onClick={() => router.push(`/admin/reports/${r.id}`)}>
              <div className="report-card-top">
                <div className="report-card-reporter">
                  <Icon name="user" size={14} />
                  <span>{r.reporter.display_name || r.reporter.username}</span>
                </div>
                <span className={`badge ${r.status === "pending" ? "badge-warning" : r.status === "resolved" ? "badge-ok" : "badge-muted"}`}>
                  {r.status === "pending" ? "대기" : r.status === "resolved" ? "처리완료" : "기각"}
                </span>
              </div>
              <div className="report-card-target">
                <span className="vis-badge" style={{ background: "var(--bg-tertiary)", padding: "1px 6px", borderRadius: 4, fontSize: 11 }}>
                  {r.target_type === "post" ? "게시글" : r.target_type === "novel" ? "시리즈" : "에피소드"}
                </span>
                <span style={{ marginLeft: 6 }}>
                  {r.target
                    ? (r.target.content ? r.target.content.slice(0, 60) : r.target.title || `#${r.target_id}`)
                    : `#${r.target_id}`}
                </span>
              </div>
              <div className="report-card-reason">{r.reason.slice(0, 100)}{r.reason.length > 100 ? "..." : ""}</div>
              <div className="report-card-footer">
                <span className="report-card-time">{r.created_at ? new Date(r.created_at).toLocaleString("ko-KR") : ""}</span>
                {r.status === "pending" && (
                  <div className="report-card-actions" onClick={(e) => e.stopPropagation()}>
                    <button className="btn btn-small btn-primary" onClick={() => handleAction(r.id, "resolve")}>
                      <Icon name="check" /> 처리
                    </button>
                    <button className="btn btn-small btn-outline" onClick={() => handleAction(r.id, "dismiss")} style={{ color: "var(--text-muted)" }}>
                      <Icon name="x" /> 기각
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
