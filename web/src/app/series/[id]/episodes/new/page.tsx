"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { useNavigationBlock } from "@/lib/useNavigationBlock";
import Icon from "@/components/Icon";
import EpisodeEditor from "@/components/EpisodeEditor";
import AudioPlayer from "@/components/AudioPlayer";
import Link from "next/link";

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

export default function NewEpisodePage() {
  const params = useParams();
  const router = useRouter();
  const audioRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [comment, setComment] = useState("");
  const [content, setContent] = useState("");
  const [isPublished, setIsPublished] = useState(true);
  const [announce, setAnnounce] = useState(false);
  const [announceComment, setAnnounceComment] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreview, setAudioPreview] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [draftId, setDraftId] = useState(0);
  const [lastSaved, setLastSaved] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftData[]>([]);
  const [showDraftList, setShowDraftList] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadedRef = useRef(false);
  const lastSavedContentRef = useRef("");

  useEffect(() => {
    if (isNaN(novelId)) return;
    api.getNovel(novelId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      setNovelTitle(d.novel.title);
    }).catch(() => router.push("/series"));
  }, [novelId, router]);

  const loadDrafts = useCallback(async () => {
    if (isNaN(novelId)) return;
    try {
      const res = await fetch(`/api/series/${novelId}/drafts`, { credentials: "include" });
      const data = await res.json();
      setDrafts(data.drafts || []);
    } catch {}
  }, [novelId]);

  useEffect(() => { loadDrafts(); }, [loadDrafts]);

  const doSave = useCallback(async () => {
    if (isNaN(novelId)) return;
    const currentContent = JSON.stringify({ title, summary, content, comment, isPublished, announce, announceComment });
    if (currentContent === lastSavedContentRef.current) return;
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
      form.append("visibility", "public");
      if (draftId) form.append("draft_id", String(draftId));
      const res = await fetch(`/api/series/${novelId}/drafts`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (data.ok) {
        setDraftId(data.draft_id);
        setLastSaved(new Date().toISOString());
        lastSavedContentRef.current = currentContent;
        loadDrafts();
      }
    } catch {}
    setSaving(false);
  }, [novelId, title, summary, content, comment, isPublished, announce, announceComment, draftId, loadDrafts]);

  useEffect(() => {
    if (!loadedRef.current) return;
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(doSave, AUTO_SAVE_DELAY);
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current); };
  }, [title, summary, content, comment, isPublished, announce, announceComment, doSave]);

  useEffect(() => { loadedRef.current = true; }, []);

  useNavigationBlock(dirty);
  useEffect(() => { if (loadedRef.current) setDirty(true); }, [title, summary, comment, content, isPublished, announce, announceComment]);

  const loadDraft = (d: DraftData) => {
    setTitle(d.title);
    setSummary(d.summary);
    setContent(d.content);
    setComment(d.comment);
    setIsPublished(d.is_published);
    setAnnounce(d.announce);
    setAnnounceComment(d.announce_comment);
    setDraftId(d.id);
    setLastSaved(d.updated_at);
    lastSavedContentRef.current = JSON.stringify({ title: d.title, summary: d.summary, content: d.content, comment: d.comment, isPublished: d.is_published, announce: d.announce, announceComment: d.announce_comment });
    setShowDraftList(false);
  };

  const deleteDraft = async (id: number) => {
    await fetch(`/api/series/${novelId}/drafts/${id}/delete`, { method: "POST", credentials: "include" });
    loadDrafts();
  };

  const handleAudioChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (audioPreview) URL.revokeObjectURL(audioPreview);
    setAudioFile(f);
    setAudioPreview(URL.createObjectURL(f));
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
      if (audioFile) form.append("audio", audioFile);
      if (announce) {
        form.append("announce", "true");
        form.append("announce_comment", announceComment);
      }
      const res = await fetch(`/api/series/${params.id}/episodes/new`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (res.ok) {
        if (draftId) await fetch(`/api/series/${novelId}/drafts/${draftId}/delete`, { method: "POST", credentials: "include" });
        setDirty(false);
        setTimeout(() => router.push(`/series/${params.id}/episodes/${data.episode_id}`), 0);
      } else alert("게시 실패");
    } catch { alert("게시 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <h2><Link href={`/series/${params.id}`} className="no-underline" style={{ color: "inherit" }}>{novelTitle || "로딩 중..."}</Link></h2>
      <form onSubmit={handleSubmit} className="episode-form">
        <div className="form-group">
          <label>에피소드 제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="에피소드 제목" />
        </div>
        <div className="form-group">
          <label>요약/스포일러 방지</label>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2} placeholder="에피소드 요약 (선택사항)" />
        </div>
        <div className="form-group">
          <label>내용 *</label>
          <EpisodeEditor value={content} onChange={(v) => setContent(v)} />
        </div>
        <div className="form-group">
          <label>작가 코멘트</label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="이 에피소드에 대한 작가의 코멘트 (선택사항)" />
        </div>
        <div className="form-group">
          <label>배경 음악</label>
          <div className="profile-edit-file-row">
            <label className="btn btn-outline profile-edit-file-label" style={{ cursor: "pointer" }}>
              파일 선택
              <input type="file" ref={audioRef} accept="audio/*" onChange={handleAudioChange} style={{ display: "none" }} />
            </label>
            {audioFile && <span className="profile-edit-file-name">{audioFile.name}</span>}
            {audioPreview && <button type="button" onClick={() => { setAudioFile(null); setAudioPreview(""); if (audioRef.current) audioRef.current.value = ""; }} style={{ color: "var(--danger)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>제거</button>}
          </div>
          {audioPreview && <AudioPlayer src={audioPreview} />}
          <p className="form-help">에피소드 본문 위에 음악 플레이어가 표시됩니다 (MP3, M4A, WAV, FLAC 등)</p>
        </div>
        <div className="form-group">
          <label className="flex-center" style={{ gap: 6, cursor: "pointer", justifyContent: "flex-start" }}>
            <input type="checkbox" checked={isPublished} onChange={(e) => setIsPublished(e.target.checked)} />
            <Icon name={isPublished ? "check" : "lock"} /> {isPublished ? "공개" : "비공개"}
          </label>
        </div>
        <div className="form-group announce-group">
          <label>
            <input type="checkbox" checked={announce} onChange={(e) => setAnnounce(e.target.checked)} />
            {" "}SNS에 홍보글 게시 (ActivityPub으로 연동됨)
          </label>
          {announce && (
            <textarea
              value={announceComment}
              onChange={(e) => setAnnounceComment(e.target.value)}
              maxLength={100}
              rows={2}
              placeholder="홍보글에 추가할 코멘트 (선택, 100자 이내)"
              className="announce-textarea"
            />
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
          <button type="submit" disabled={submitting || !title.trim() || !(content || "").trim()} className="btn btn-primary">게시</button>
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
