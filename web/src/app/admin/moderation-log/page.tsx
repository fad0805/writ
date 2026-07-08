"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

export default function AdminModerationLogPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState("");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const limit = 50;

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const loadLogs = async (append = false) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ offset: String(page * limit), limit: String(limit) });
      if (actionFilter) params.set("action", actionFilter);
      const res = await fetch(`/api/admin/logs?${params}`, { credentials: "include" });
      if (res.ok) {
        const d = await res.json();
        setLogs(append ? [...logs, ...d.logs] : d.logs);
        setHasMore(d.has_more);
      }
    } catch {}
    setLoading(false);
  };

  useEffect(() => { if (!authLoading) { setPage(0); loadLogs(); } }, [authLoading, actionFilter]);

  const loadMore = () => { setPage(p => p + 1); loadLogs(true); };

  const actionLabels: Record<string, string> = {
    login: "로그인", login_failed: "로그인 실패", login_blocked: "로그인 차단",
    register: "가입", change_email: "이메일 변경", change_password: "비밀번호 변경",
    suspend: "정지", unsuspend: "정지 해제", moderate: "중재",
    delete_user: "회원 삭제", delete_post: "게시글 삭제",
    set_note: "메모 설정", toggle_sensitive: "민감 전환",
    block_domain: "도메인 차단", unblock_domain: "도메인 차단 해제",
    federation_block: "연합 차단", federation_unblock: "연합 차단 해제",
    federation_allow: "연합 허용", federation_disallow: "연합 허용 해제",
    federation_mode: "연합 모드 변경",
    change_role: "권한 변경", reset_password: "비밀번호 초기화",
    admin_change_email: "이메일 강제 변경", verify_email: "이메일 인증",
    remove_avatar: "아바타 제거", resolve_report: "신고 처리", dismiss_report: "신고 기각",
    set_post_cw: "CW 설정", update_settings: "서버 설정 변경",
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="activity" /> 중재 기록</h2></div>
      <AdminNav current="moderation-log" />
      <div style={{ marginBottom: 12, display: "flex", gap: 6, alignItems: "center" }}>
        <select value={actionFilter} onChange={e => { setActionFilter(e.target.value); setPage(0); }} className="cw-input" style={{ width: 180 }}>
          <option value="">전체</option>
          {Object.entries(actionLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span style={{ fontSize: "0.85em", color: "var(--text-muted)" }}>{logs.length}개</span>
      </div>
      <div className="admin-table">
        <div className="admin-table-header">
          <span style={{ width: 140 }}>시간</span>
          <span style={{ width: 80 }}>사용자</span>
          <span style={{ width: 100 }}>액션</span>
          <span style={{ width: 80 }}>대상</span>
          <span style={{ flex: 1 }}>상세</span>
          <span style={{ width: 100 }}>IP</span>
        </div>
        {logs.map((log: any) => (
          <div key={log.id} className="admin-table-row">
            <span style={{ width: 140, fontSize: "0.85em", fontFamily: "monospace" }}>{log.created_at?.slice(0, 19) || "-"}</span>
            <span style={{ width: 80 }}>{log.username || "-"}</span>
            <span style={{ width: 100 }}>{actionLabels[log.action] || log.action}</span>
            <span style={{ width: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{log.target_username || "-"}</span>
            <span style={{ flex: 1, fontSize: "0.85em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{log.details || "-"}</span>
            <span style={{ width: 100, fontSize: "0.85em", fontFamily: "monospace" }}>{log.ip_address || ""}</span>
          </div>
        ))}
      </div>
      {hasMore && <div className="form-actions"><button onClick={loadMore} className="btn btn-outline">더 보기</button></div>}
    </>
  );
}
