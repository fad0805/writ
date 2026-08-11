"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

const INITIAL_LIMIT = 100;
const PAGE_LIMIT = 50;

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

interface ModerationLog {
  id: number;
  created_at?: string;
  username?: string;
  action: string;
  target_username?: string;
  details?: string;
  ip_address?: string;
}

export default function AdminModerationLogPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [logs, setLogs] = useState<ModerationLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState("");
  const [mode, setMode] = useState<"initial" | "paged">("initial");
  const [pagedPage, setPagedPage] = useState(0);

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const loadInitial = async () => {
    setLoading(true); setMode("initial");
    try {
      const params = new URLSearchParams({ offset: "0", limit: String(INITIAL_LIMIT) });
      if (actionFilter) params.set("action", actionFilter);
      const res = await fetch(`/api/admin/logs?${params}`, { credentials: "include" });
      if (res.ok) { const d = await res.json(); setLogs(d.logs); setTotal(d.total || 0); }
    } catch {}
    setLoading(false);
  };

  const loadPage = async (pageNum: number) => {
    setLoading(true); setMode("paged"); setPagedPage(pageNum);
    try {
      const params = new URLSearchParams({ offset: String(INITIAL_LIMIT + pageNum * PAGE_LIMIT), limit: String(PAGE_LIMIT) });
      if (actionFilter) params.set("action", actionFilter);
      const res = await fetch(`/api/admin/logs?${params}`, { credentials: "include" });
      if (res.ok) { const d = await res.json(); setLogs(d.logs); }
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    if (!authLoading) {
      let cancelled = false;
      (async () => {
        try {
          const params = new URLSearchParams({ offset: "0", limit: String(INITIAL_LIMIT) });
          if (actionFilter) params.set("action", actionFilter);
          const res = await fetch(`/api/admin/logs?${params}`, { credentials: "include" });
          if (!cancelled) setMode("initial");
          if (res.ok) { const d = await res.json(); if (!cancelled) { setLogs(d.logs); setTotal(d.total || 0); } }
        } catch {}
        if (!cancelled) setLoading(false);
      })();
      return () => { cancelled = true; };
    }
  }, [authLoading, actionFilter]);

  const totalPages = Math.max(0, Math.ceil((total - INITIAL_LIMIT) / PAGE_LIMIT));

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="moderation-log" />
      <div style={{ marginBottom: 12, display: "flex", gap: 6, alignItems: "center" }}>
        <select value={actionFilter} onChange={e => { setActionFilter(e.target.value); }} className="cw-input" style={{ width: 180 }}>
          <option value="">전체</option>
          {Object.entries(actionLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span style={{ fontSize: "0.85em", color: "var(--text-muted)" }}>{total}개</span>
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
        {logs.map((log: ModerationLog) => (
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
      {mode === "initial" && total > INITIAL_LIMIT && (
        <div className="form-actions"><button onClick={() => loadPage(0)} className="btn btn-outline">더보기 (이전 기록)</button></div>
      )}
      {mode === "paged" && (
        <div className="form-actions" style={{ gap: 4 }}>
          <button disabled={pagedPage === 0} onClick={() => loadPage(pagedPage - 1)} className="btn btn-small btn-outline">←</button>
          <span style={{ fontSize: "0.85em", color: "var(--text-muted)", padding: "0 8px" }}>{pagedPage + 1} / {totalPages}</span>
          <button disabled={pagedPage >= totalPages - 1} onClick={() => loadPage(pagedPage + 1)} className="btn btn-small btn-outline">→</button>
          <button onClick={loadInitial} className="btn btn-small btn-outline" style={{ marginLeft: 8 }}>최근 기록</button>
        </div>
      )}
    </>
  );
}
