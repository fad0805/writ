"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import Icon from "@/components/Icon";
import EpisodeEditor from "@/components/EpisodeEditor";
import Link from "next/link";

const DRAFT_KEY_PREFIX = "ep-draft-";
const AUTO_SAVE_DELAY = 3000;

function getDraftKey(novelId: number) { return `${DRAFT_KEY_PREFIX}${novelId}`; }

function saveDraft(key: string, data: Record<string, any>) {
  try { localStorage.setItem(key, JSON.stringify({ ...data, savedAt: Date.now() })); } catch {}
}

function loadDraft(key: string) {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : null; } catch { return null; }
}

function clearDraft(key: string) { try { localStorage.removeItem(key); } catch {} }

function formatTime(ts: number) {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export default function NewEpisodePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [comment, setComment] = useState("");
  const [content, setContent] = useState("");
  const [isPublished, setIsPublished] = useState(true);
  const [announce, setAnnounce] = useState(false);
  const [announceComment, setAnnounceComment] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [lastSaved, setLastSaved] = useState<number | null>(null);
  const [showRestored, setShowRestored] = useState(false);
  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const draftKey = getDraftKey(novelId);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (isNaN(novelId)) return;
    api.getNovel(novelId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      setNovelTitle(d.novel.title);
    }).catch(() => router.push("/series"));
  }, [novelId, router]);

  const doSave = useCallback(() => {
    saveDraft(draftKey, { title, summary, content, comment, isPublished, announce, announceComment });
    setLastSaved(Date.now());
  }, [draftKey, title, summary, content, comment, isPublished, announce, announceComment]);

  useEffect(() => {
    if (!loadedRef.current) return;
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(doSave, AUTO_SAVE_DELAY);
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current); };
  }, [title, summary, content, comment, isPublished, announce, announceComment, doSave]);

  useEffect(() => {
    if (isNaN(novelId)) return;
    const draft = loadDraft(draftKey);
    if (draft) {
      setTitle(draft.title || "");
      setSummary(draft.summary || "");
      setContent(draft.content || "");
      setComment(draft.comment || "");
      setIsPublished(draft.isPublished !== undefined ? draft.isPublished : true);
      setAnnounce(draft.announce || false);
      setAnnounceComment(draft.announceComment || "");
      setLastSaved(draft.savedAt);
      setShowRestored(true);
    }
    loadedRef.current = true;
  }, [novelId, draftKey]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanContent = content.replace(/<[^>]*>/g, "").trim();
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
      const res = await fetch(`/api/series/${params.id}/episodes/new`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (res.ok) { clearDraft(draftKey); router.push(`/series/${params.id}/episodes/${data.episode_id}`); }
      else alert("게시 실패");
    } catch { alert("게시 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <h2><Link href={`/series/${params.id}`} className="no-underline" style={{ color: "inherit" }}>{novelTitle || "로딩 중..."}</Link></h2>
      {showRestored && (
        <div className="draft-banner">
          <Icon name="check" /> 임시 저장된 글이 있습니다{lastSaved ? ` (${formatTime(lastSaved)} 저장)` : ""}.
          <button className="btn btn-small btn-outline" onClick={() => setShowRestored(false)}>이어서 쓰기</button>
          <button className="btn btn-small" onClick={() => { clearDraft(draftKey); setTitle(""); setSummary(""); setContent(""); setComment(""); setShowRestored(false); }}>비우기</button>
        </div>
      )}
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
          <button type="button" onClick={doSave} className="btn btn-outline"><Icon name="check" /> 임시저장{lastSaved ? ` (${formatTime(lastSaved)})` : ""}</button>
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">게시</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
