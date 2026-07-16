"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { useBeforeUnload } from "@/lib/useBeforeUnload";
import EpisodeEditor from "@/components/EpisodeEditor";
import VisibilitySelector from "@/components/VisibilitySelector";
import Icon from "@/components/Icon";

const AUTO_SAVE_DELAY = 3000;

interface DraftData {
  id: number;
  title: string;
  summary: string;
  content: string;
  comment: string;
  is_published: boolean;
  announce: boolean;
  announce_comment: string;
  visibility: string;
  episode_id: number | null;
  created_at: string;
  updated_at: string;
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${formatTime(iso)}`;
}

export default function EditEpisodePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [comment, setComment] = useState("");
  const [content, setContent] = useState("");
  const [isPublished, setIsPublished] = useState(true);
  const [novelTitle, setNovelTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [announce, setAnnounce] = useState(false);
  const [visibility, setVisibility] = useState("public");
  const [announceComment, setAnnounceComment] = useState("");
  const [dirty, setDirty] = useState(false);
  const [draftId, setDraftId] = useState(0);
  const [lastSaved, setLastSaved] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftData[]>([]);
  const [showDraftList, setShowDraftList] = useState(false);
  const [saving, setSaving] = useState(false);
  const loadedRef = useRef(false);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const episodeId = Number(Array.isArray(params.eid) ? params.eid[0] : params.eid);

  useBeforeUnload(dirty);
  useEffect(() => { if (!loading) loadedRef.current = true; }, [loading]);
  useEffect(() => { if (loadedRef.current) setDirty(true); }, [title, summary, comment, content, isPublished, announce, announceComment, visibility]);

  useEffect(() => {
    if (isNaN(novelId) || isNaN(episodeId)) return;
    api.getNovel(novelId).then((d) => {
      const ep = d.episodes.find((e: any) => e.id === episodeId);
      if (!ep || !d.is_mine) { router.push(`/series/${novelId}`); return; }
      setTitle(ep.title);
      setSummary(ep.summary || "");
      setComment(ep.comment || "");
      setContent(ep.content || "");
      setIsPublished(ep.is_published);
      setNovelTitle(d.novel.title);
      setLoading(false);
    }).catch(() => router.push("/series"));
  }, [novelId, episodeId, router]);

  const loadDrafts = useCallback(async () => {
    if (isNaN(novelId)) return;
    try {
      const res = await fetch(`/api/series/${novelId}/drafts`, { credentials: "include" });
      const data = await res.json();
      setDrafts((data.drafts || []).filter((d: DraftData) => d.episode_id === episodeId));
    } catch {}
  }, [novelId, episodeId]);

  useEffect(() => { if (!loading) loadDrafts(); }, [loading, loadDrafts]);

  const doSave = useCallback(async () => {
    if (isNaN(novelId)) return;
    setSaving(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("summary", summary);
      form.append("content", content);
      form.append("comment", comment);
      form.append("is_published", String(isPublished));
      form.append("announce", String(announce));
      form.append("announce_comment", announceComment);
      form.append("visibility", visibility);
      form.append("episode_id", String(episodeId));
      if (draftId) form.append("draft_id", String(draftId));
      const res = await fetch(`/api/series/${novelId}/drafts`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (data.ok) {
        setDraftId(data.draft_id);
        setLastSaved(new Date().toISOString());
        loadDrafts();
      }
    } catch {}
    setSaving(false);
  }, [novelId, episodeId, title, summary, content, comment, isPublished, announce, announceComment, visibility, draftId, loadDrafts]);

  useEffect(() => {
    if (!loadedRef.current) return;
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(doSave, AUTO_SAVE_DELAY);
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current); };
  }, [title, summary, content, comment, isPublished, announce, announceComment, visibility, doSave]);

  const loadDraft = (d: DraftData) => {
    setTitle(d.title);
    setSummary(d.summary);
    setContent(d.content);
    setComment(d.comment);
    setIsPublished(d.is_published);
    setAnnounce(d.announce);
    setAnnounceComment(d.announce_comment);
    if (d.visibility) setVisibility(d.visibility);
    setDraftId(d.id);
    setLastSaved(d.updated_at);
    setShowDraftList(false);
  };

  const deleteDraft = async (id: number) => {
    await fetch(`/api/series/${novelId}/drafts/${id}/delete`, { method: "POST", credentials: "include" });
    loadDrafts();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanContent = (content || "").replace(/<[^>]*>/g, "").trim();
    if (!title.trim() || !cleanContent || submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("content", content);
      form.append("summary", summary);
      form.append("comment", comment);
      form.append("is_published", isPublished ? "true" : "false");
      if (announce) {
        form.append("announce", "true");
        form.append("announce_comment", announceComment);
      }
      form.append("visibility", visibility);
      const res = await fetch(`/api/series/${params.id}/episodes/${params.eid}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        if (draftId) await fetch(`/api/series/${novelId}/drafts/${draftId}/delete`, { method: "POST", credentials: "include" });
        setDirty(false);
        router.push(`/series/${params.id}/episodes/${params.eid}`);
      } else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <h2>{novelTitle}</h2>
      <form onSubmit={handleSubmit} className="episode-form">
        <div className="form-group">
          <label>에피소드 제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="form-group">
          <label>요약</label>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2} />
        </div>
        <div className="form-group">
          <label>내용</label>
          <EpisodeEditor value={content} onChange={(v) => setContent(v)} />
        </div>
        <div className="form-group">
          <label>작가 코멘트</label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="이 에피소드에 대한 작가의 코멘트 (선택사항)" />
        </div>
        <div className="form-group">
          <label>
            <input type="checkbox" checked={isPublished} onChange={(e) => setIsPublished(e.target.checked)} />
            {" "}공개
          </label>
        </div>
        <div className="form-group announce-group">
          <label>
            <input type="checkbox" checked={announce} onChange={(e) => setAnnounce(e.target.checked)} />
            {" "}SNS에 홍보글 게시 (ActivityPub으로 연동됨)
          </label>
          {announce && (
            <>
              <textarea
                value={announceComment}
                onChange={(e) => setAnnounceComment(e.target.value)}
                maxLength={100}
                rows={2}
                placeholder="홍보글에 추가할 코멘트 (선택, 100자 이내)"
                className="announce-textarea"
              />
              <div className="announce-vis-wrap">
                <VisibilitySelector value={visibility} onChange={(v) => setVisibility(v)} />
              </div>
            </>
          )}
        </div>
        <div className="form-actions">
          <div className="draft-actions">
            <button type="button" onClick={doSave} className="btn btn-outline" disabled={saving}>
              <Icon name="check" /> 임시저장{lastSaved ? ` (${formatTime(lastSaved)})` : ""}
            </button>
            {drafts.length > 0 && (
              <button type="button" onClick={() => setShowDraftList(!showDraftList)} className="btn btn-outline">
                <Icon name="book" /> 임시저장 목록 ({drafts.length})
              </button>
            )}
          </div>
          <button type="submit" disabled={submitting || !title.trim() || !(content || "").trim()} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
        {showDraftList && (
          <div className="draft-list">
            {drafts.map((d) => (
              <div key={d.id} className="draft-list-item">
                <div className="draft-list-info" onClick={() => loadDraft(d)}>
                  <span className="draft-list-title">{d.title || "제목 없음"}</span>
                  <span className="draft-list-date">{formatDate(d.updated_at)}</span>
                </div>
                <button type="button" className="draft-list-delete" onClick={() => deleteDraft(d.id)}><Icon name="trash" /></button>
              </div>
            ))}
          </div>
        )}
      </form>
    </>
  );
}
