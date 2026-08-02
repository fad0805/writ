"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import AdminNav from "@/components/AdminNav";
import Icon from "@/components/Icon";
import { Announcement, toInputValue, fmtAnnouncementTime } from "@/lib/announcements";

export default function AdminAnnouncementsPage() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ title: "", content: "", starts_at: "", ends_at: "" });
  const [pollOptions, setPollOptions] = useState<string[]>(["", ""]);
  const pollLastRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/announcements", { credentials: "include" });
      if (res.ok) setItems(await res.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const resetForm = () => {
    setForm({ title: "", content: "", starts_at: "", ends_at: "" });
    setPollOptions(["", ""]);
  };

  const submitForm = async () => {
    if (!form.title.trim()) return;
    const isEdit = editingId !== null;
    const fd = new FormData();
    fd.append("title", form.title);
    fd.append("content", form.content);
    fd.append("starts_at", form.starts_at);
    fd.append("ends_at", form.ends_at);
    const opts = pollOptions.filter((o) => o.trim());
    fd.append("poll_options", opts.length >= 2 ? JSON.stringify(opts.map((o) => o.trim())) : "");
    const url = isEdit ? `/api/admin/announcements/${editingId}/edit` : "/api/admin/announcements/new";
    const res = await fetch(url, { method: "POST", credentials: "include", body: fd });
    if (res.ok) {
      const saved = await res.json();
      if (isEdit) {
        setItems((prev) => prev.map((x) => (x.id === saved.id ? saved : x)));
        setEditingId(null);
      } else {
        setItems((prev) => [saved, ...prev]);
      }
      setShowNew(false);
      resetForm();
      window.dispatchEvent(new Event("announcementchange"));
    }
  };

  const startEdit = (a: Announcement) => {
    setEditingId(a.id);
    setShowNew(true);
    setForm({ title: a.title, content: a.content, starts_at: toInputValue(a.starts_at), ends_at: toInputValue(a.ends_at) });
    setPollOptions(a.poll_data?.options?.map((o) => o.text)?.length ? a.poll_data.options.map((o) => o.text) : ["", ""]);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setShowNew(false);
    resetForm();
  };

  const handleDelete = async (a: Announcement) => {
    if (!confirm(`"${a.title}" 공지사항을 삭제하시겠습니까?`)) return;
    const res = await fetch(`/api/admin/announcements/${a.id}/delete`, { method: "POST", credentials: "include" });
    if (res.ok) {
      setItems((prev) => prev.filter((x) => x.id !== a.id));
      window.dispatchEvent(new Event("announcementchange"));
    }
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>
      <AdminNav current="announcements" />
      {!showNew && (
        <button className="btn btn-primary btn-small" style={{ marginBottom: 12 }} onClick={() => { setShowNew(true); setEditingId(null); resetForm(); }}>
          새 공지사항
        </button>
      )}
      {showNew && (
        <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 12 }}>
          <div className="form-group">
            <label>제목</label>
            <input type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="공지사항 제목" maxLength={256} />
          </div>
          <div className="form-group">
            <label>내용</label>
            <textarea value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} rows={5} placeholder="공지사항 내용" style={{ width: "100%", resize: "vertical" }} />
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
            <div className="form-group" style={{ flex: 1, minWidth: 180 }}>
              <label>노출 시작 시간 (선택)</label>
              <input type="datetime-local" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
            </div>
            <div className="form-group" style={{ flex: 1, minWidth: 180 }}>
              <label>노출 종료 시간 (선택)</label>
              <input type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
            </div>
          </div>
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>시작/종료 시간을 설정하지 않으면 무기한 노출됩니다.</p>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", marginBottom: 4 }}>투표 (선택)</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {pollOptions.map((opt, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="text"
                    value={opt}
                    placeholder={`선택지 ${i + 1}`}
                    maxLength={100}
                    ref={i === pollOptions.length - 1 ? pollLastRef : undefined}
                    onChange={(e) => {
                      const next = [...pollOptions];
                      next[i] = e.target.value;
                      setPollOptions(next);
                      if (i === pollOptions.length - 1 && e.target.value.trim() && pollOptions.length < 10) {
                        setPollOptions([...next, ""]);
                        setTimeout(() => pollLastRef.current?.focus(), 0);
                      }
                    }}
                    style={{ flex: 1, minWidth: 0 }}
                  />
                  {pollOptions.length > 2 && (
                    <button type="button" onClick={() => setPollOptions(pollOptions.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "var(--danger)", cursor: "pointer", fontSize: 16 }}>×</button>
                  )}
                </div>
              ))}
              {pollOptions.length < 10 && (
                <button type="button" className="action-btn" onClick={() => { setPollOptions([...pollOptions, ""]); setTimeout(() => pollLastRef.current?.focus(), 0); }} style={{ fontSize: 12, alignSelf: "flex-start" }}>+ 선택지 추가</button>
              )}
            </div>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>선택지가 2개 이상일 때 투표가 표시됩니다.</p>
          </div>
          <div className="form-actions">
            <button onClick={submitForm} disabled={!form.title.trim()} className="btn btn-primary">{editingId ? "저장" : "등록"}</button>
            <button onClick={cancelEdit} className="btn btn-outline">취소</button>
          </div>
        </div>
      )}
      {items.length === 0 ? (
        <p className="empty-state">등록된 공지사항이 없습니다.</p>
      ) : (
        items.map((a) => (
          <div key={a.id} style={{ background: "var(--bg-secondary)", border: `1px solid ${a.active ? "var(--accent)" : "var(--border)"}`, borderRadius: 8, padding: 12, marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <strong>{a.title}</strong>
              {a.poll_data?.options?.length ? <span title="투표 포함"><Icon name="chart" size={14} /></span> : null}
              <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 4, background: a.active ? "var(--accent)" : "var(--border)", color: a.active ? "#fff" : "var(--text-muted)" }}>
                {a.active ? "노출 중" : "노출 종료"}
              </span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                <button className="action-btn" onClick={() => startEdit(a)}><Icon name="edit" /></button>
                <button className="action-btn text-muted" onClick={() => handleDelete(a)}><Icon name="trash" /></button>
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
              시작: {fmtAnnouncementTime(a.starts_at) || "무기한"} · 종료: {fmtAnnouncementTime(a.ends_at) || "무기한"}
            </div>
            {a.content && <p style={{ margin: "6px 0 0", fontSize: "0.85em", color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>{a.content}</p>}
          </div>
        ))
      )}
    </>
  );
}
