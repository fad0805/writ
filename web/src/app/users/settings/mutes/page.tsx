"use client";
import { useState, useEffect } from "react";
import Icon from "@/components/Icon";
import SettingsNav from "@/components/SettingsNav";
import Avatar from "@/components/Avatar";
import { useAuth } from "@/lib/auth";

type Tab = "user-mutes" | "user-blocks" | "series-mutes" | "keyword-mutes";

interface MutedUser { id: number; target_user_id: number; username: string; display_name: string; avatar: string; duration: number; hide_notifications: boolean; created_at: string | null; }
interface BlockedUser { id: number; target_user_id: number; username: string; display_name: string; avatar: string; created_at: string | null; }
interface MutedSeries { id: number; novel_id: number; title: string; cover_image: string; created_at: string | null; }
interface KeywordMuteItem { id: number; keyword: string; mode: string; is_regex: boolean; created_at: string | null; }

export default function MutesSettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const [tab, setTab] = useState<Tab>("user-mutes");
  const [mutedUsers, setMutedUsers] = useState<MutedUser[]>([]);
  const [blockedUsers, setBlockedUsers] = useState<BlockedUser[]>([]);
  const [mutedSeries, setMutedSeries] = useState<MutedSeries[]>([]);
  const [keywordMutes, setKeywordMutes] = useState<KeywordMuteItem[]>([]);
  const [newKeyword, setNewKeyword] = useState("");
  const [keywordMode, setKeywordMode] = useState<"and" | "or">("or");
  const [keywordIsRegex, setKeywordIsRegex] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    Promise.all([
      fetch("/api/mutes/users", { credentials: "include" }).then(r => r.json()).then(d => setMutedUsers(d.mutes || [])).catch(() => {}),
      fetch("/api/blocks/users", { credentials: "include" }).then(r => r.json()).then(d => setBlockedUsers(d.blocks || [])).catch(() => {}),
      fetch("/api/mutes/series", { credentials: "include" }).then(r => r.json()).then(d => setMutedSeries(d.mutes || [])).catch(() => {}),
      fetch("/api/mutes/keywords", { credentials: "include" }).then(r => r.json()).then(d => setKeywordMutes(d.mutes || [])).catch(() => {}),
    ]).then(() => setLoading(false));
  }, [authLoading]);

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user) return <div className="empty-state">로그인이 필요합니다.</div>;

  const TABS: { key: Tab; label: string; icon: string; count: number }[] = [
    { key: "user-mutes", label: "사용자 뮤트", icon: "mute", count: mutedUsers.length },
    { key: "user-blocks", label: "사용자 블락", icon: "block", count: blockedUsers.length },
    { key: "series-mutes", label: "시리즈 뮤트", icon: "book", count: mutedSeries.length },
    { key: "keyword-mutes", label: "키워드 뮤트", icon: "tag", count: keywordMutes.length },
  ];

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 설정 관리</h2></div>
      <SettingsNav current="mutes" />
      <div className="admin-tabs" style={{ marginBottom: 16 }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} className={`btn btn-small ${tab === t.key ? "btn-primary" : "btn-outline"}`}>
            <Icon name={t.icon} /> {t.label} ({t.count})
          </button>
        ))}
      </div>

      {tab === "user-mutes" && (
        <div className="novel-form">
          {mutedUsers.length === 0 ? <p className="empty-small">뮤트한 사용자가 없습니다.</p> : mutedUsers.map(m => (
            <div key={m.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 6, marginBottom: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Avatar user={{ username: m.username, display_name: m.display_name, avatar: m.avatar } as any} className="sidebar-avatar rounded-[8px]" style={{ width: 28, height: 28, minWidth: 28 }} />
                <span><strong>{m.display_name}</strong> @{m.username}</span>
              </div>
              <button onClick={async () => { await fetch(`/api/mutes/users/${m.target_user_id}`, { method: "DELETE", credentials: "include" }); setMutedUsers(prev => prev.filter(x => x.id !== m.id)); }} className="btn btn-small btn-outline text-xs">해제</button>
            </div>
          ))}
        </div>
      )}

      {tab === "user-blocks" && (
        <div className="novel-form">
          {blockedUsers.length === 0 ? <p className="empty-small">블락한 사용자가 없습니다.</p> : blockedUsers.map(b => (
            <div key={b.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 6, marginBottom: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Avatar user={{ username: b.username, display_name: b.display_name, avatar: b.avatar } as any} className="sidebar-avatar rounded-[8px]" style={{ width: 28, height: 28, minWidth: 28 }} />
                <span><strong>{b.display_name}</strong> @{b.username}</span>
              </div>
              <button onClick={async () => { await fetch(`/api/blocks/users/${b.target_user_id}`, { method: "DELETE", credentials: "include" }); setBlockedUsers(prev => prev.filter(x => x.id !== b.id)); }} className="btn btn-small btn-outline text-xs">해제</button>
            </div>
          ))}
        </div>
      )}

      {tab === "series-mutes" && (
        <div className="novel-form">
          {mutedSeries.length === 0 ? <p className="empty-small">뮤트한 시리즈가 없습니다.</p> : mutedSeries.map(s => (
            <div key={s.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 6, marginBottom: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {s.cover_image ? (
                  <img src={s.cover_image} alt="" style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover" }} />
                ) : (
                  <div style={{ width: 28, height: 28, borderRadius: 6, background: "var(--bg-secondary)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: "0.8em" }}><Icon name="book" size={14} /></div>
                )}
                <span>{s.title}</span>
              </div>
              <button onClick={async () => { await fetch(`/api/mutes/series/${s.novel_id}`, { method: "DELETE", credentials: "include" }); setMutedSeries(prev => prev.filter(x => x.id !== s.id)); }} className="btn btn-small btn-outline text-xs">해제</button>
            </div>
          ))}
        </div>
      )}

      {tab === "keyword-mutes" && (
        <div className="novel-form">
          <form onSubmit={async (e) => { e.preventDefault(); if (!newKeyword.trim()) return; const params = new URLSearchParams({ keyword: newKeyword.trim(), mode: keywordMode }); if (keywordIsRegex) params.set("is_regex", "true"); const res = await fetch("/api/mutes/keywords", { method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: params }); if (res.ok) { setNewKeyword(""); fetch("/api/mutes/keywords", { credentials: "include" }).then(r => r.json()).then(d => setKeywordMutes(d.mutes || [])); } }} style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
            <input type="text" value={newKeyword} onChange={e => setNewKeyword(e.target.value)} placeholder="키워드 (쉼표 구분)" className="cw-input" style={{ flex: 1, minWidth: 200 }} required />
            <select value={keywordMode} onChange={e => setKeywordMode(e.target.value as "and" | "or")} className="cw-input" style={{ width: 100 }}>
              <option value="or">OR</option>
              <option value="and">AND</option>
            </select>
            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "0.85em", color: "var(--text-muted)", cursor: "pointer" }}>
              <input type="checkbox" checked={keywordIsRegex} onChange={e => setKeywordIsRegex(e.target.checked)} /> 정규식
            </label>
            <button type="submit" className="btn btn-primary btn-small">추가</button>
          </form>
          {keywordMutes.length === 0 ? <p className="empty-small">차단한 키워드가 없습니다.</p> : keywordMutes.map(k => (
            <div key={k.id} className="admin-table-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 6, marginBottom: 4 }}>
              <span style={{ fontSize: "0.9em" }}><Icon name="tag" size={13} /> {k.keyword} <span style={{ color: "var(--text-dim)", fontSize: "0.85em" }}>({k.mode === "and" ? "AND" : "OR"}{k.is_regex ? ", 정규식" : ""})</span></span>
              <button onClick={async () => { await fetch(`/api/mutes/keywords/${k.id}`, { method: "DELETE", credentials: "include" }); setKeywordMutes(prev => prev.filter(x => x.id !== k.id)); }} className="btn btn-small btn-outline text-xs">삭제</button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
