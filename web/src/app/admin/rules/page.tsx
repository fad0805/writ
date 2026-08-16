"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import AdminNav from "@/components/AdminNav";
import Icon from "@/components/Icon";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/permissions";

interface Rule {
  id: number;
  title: string;
  description: string;
  sort_order: number;
}

export default function AdminRulesPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/admin/rules", { credentials: "include" });
        if (res.ok) { const d = await res.json(); if (!cancelled) setRules(d); }
      } catch {}
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authLoading && !isStaff(user)) {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const handleReorder = async (newRules: Rule[]) => {
    setRules(newRules);
    await fetch("/api/admin/rules/reorder", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ rule_ids: JSON.stringify(newRules.map((r) => r.id)) }),
    });
  };

  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    if (dragIdx === null || dragIdx === idx) return;
    const next = [...rules];
    const [moved] = next.splice(dragIdx, 1);
    next.splice(idx, 0, moved);
    setDragIdx(idx);
    handleReorder(next);
  };
  const handleDragEnd = () => setDragIdx(null);

  const toggleEdit = (r: Rule) => {
    if (editingId === r.id) {
      setEditingId(null);
      return;
    }
    setEditingId(r.id);
    setEditTitle(r.title);
    setEditDesc(r.description);
  };

  const saveEdit = async (r: Rule) => {
    const form = new FormData();
    form.append("title", editTitle);
    form.append("description", editDesc);
    const res = await fetch(`/api/admin/rules/${r.id}/edit`, { method: "POST", credentials: "include", body: form });
    if (res.ok) {
      setRules((prev) => prev.map((x) => (x.id === r.id ? { ...x, title: editTitle, description: editDesc } : x)));
      setEditingId(null);
    }
  };

  const handleDelete = async (r: Rule) => {
    if (!confirm(`"${r.title}" 규칙을 삭제하시겠습니까?`)) return;
    const res = await fetch(`/api/admin/rules/${r.id}/delete`, { method: "POST", credentials: "include" });
    if (res.ok) setRules((prev) => prev.filter((x) => x.id !== r.id));
  };

  const createRule = async () => {
    if (!newTitle.trim()) return;
    const form = new FormData();
    form.append("title", newTitle);
    form.append("description", newDesc);
    const res = await fetch("/api/admin/rules/new", { method: "POST", credentials: "include", body: form });
    if (res.ok) {
      const created = await res.json();
      setRules((prev) => [...prev, created]);
      setNewTitle("");
      setNewDesc("");
      setShowNew(false);
    }
  };

  if (authLoading) return <p className="empty-state">로딩 중...</p>;
  if (!user || !isStaff(user)) return null;
  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>
      <AdminNav current="rules" user={user} />
      {!showNew && (
        <button className="btn btn-primary btn-small" style={{ marginBottom: 12 }} onClick={() => setShowNew(true)}>새 규칙</button>
      )}
      {showNew && (
        <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 12 }}>
          <div className="form-group">
            <label>규칙 제목</label>
            <input type="text" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="예: 스팸 금지" />
          </div>
          <div className="form-group">
            <label>설명 (선택)</label>
            <textarea value={newDesc} onChange={(e) => setNewDesc(e.target.value)} rows={2} placeholder="규칙에 대한 상세 설명" style={{ width: "100%", resize: "vertical" }} />
          </div>
          <div className="form-actions">
            <button onClick={createRule} disabled={!newTitle.trim()} className="btn btn-primary">추가</button>
            <button onClick={() => { setShowNew(false); setNewTitle(""); setNewDesc(""); }} className="btn btn-outline">취소</button>
          </div>
        </div>
      )}
      {rules.map((r, idx) => (
        <div key={r.id} draggable style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 6, cursor: "grab", opacity: dragIdx === idx ? 0.5 : 1 }}
          onDragStart={() => handleDragStart(idx)} onDragOver={(e) => handleDragOver(e, idx)} onDragEnd={handleDragEnd}>
          {editingId === r.id ? (
            <>
              <div className="form-group">
                <label>규칙 제목</label>
                <input type="text" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
              </div>
              <div className="form-group">
                <label>설명</label>
                <textarea value={editDesc} onChange={(e) => setEditDesc(e.target.value)} rows={2} style={{ width: "100%", resize: "vertical" }} />
              </div>
              <div className="form-actions">
                <button onClick={() => saveEdit(r)} className="btn btn-primary btn-small">저장</button>
                <button onClick={() => setEditingId(null)} className="btn btn-outline btn-small">취소</button>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "var(--text-muted)", cursor: "grab", userSelect: "none" }}>⠿</span>
                <strong>{r.title}</strong>
                <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                  <button className="action-btn" onClick={() => toggleEdit(r)}><Icon name="edit" /></button>
                  <button className="action-btn text-muted" onClick={() => handleDelete(r)}><Icon name="trash" /></button>
                </span>
              </div>
              {r.description && <p style={{ margin: "4px 0 0", fontSize: "0.85em", color: "var(--text-muted)" }}>{r.description}</p>}
            </>
          )}
        </div>
      ))}
    </>
  );
}
