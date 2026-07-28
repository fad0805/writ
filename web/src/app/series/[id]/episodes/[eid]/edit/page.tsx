"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { useNavigationBlock } from "@/lib/useNavigationBlock";
import EpisodeEditor from "@/components/EpisodeEditor";
import AudioPlayer from "@/components/AudioPlayer";
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
  const audioRef = useRef<HTMLInputElement>(null);
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
  const [audioUrl, setAudioUrl] = useState("");
  const [removeAudio, setRemoveAudio] = useState(false);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreview, setAudioPreview] = useState("");
  const [dirty, setDirty] = useState(false);
  const [pageMode, setPageMode] = useState(false);
  const [viewMode, setViewMode] = useState<"text" | "comic">("text");
  const [comicViewMode, setComicViewMode] = useState<"paged" | "scroll">("paged");
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [imageFiles, setImageFiles] = useState<File[]>([]);
  const [uploadingImages, setUploadingImages] = useState(false);
  const [readingDirection, setReadingDirection] = useState<"ltr" | "rtl">("ltr");
  const [draftId, setDraftId] = useState(0);
  const [lastSaved, setLastSaved] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftData[]>([]);
  const [showDraftList, setShowDraftList] = useState(false);
  const [saving, setSaving] = useState(false);
  const loadedRef = useRef(false);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedContentRef = useRef("");
  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const episodeId = Number(Array.isArray(params.eid) ? params.eid[0] : params.eid);

  const { suppress } = useNavigationBlock(dirty);
  useEffect(() => { if (!loading) loadedRef.current = true; }, [loading]);
  useEffect(() => { if (loadedRef.current) setDirty(true); }, [title, summary, comment, content, isPublished, announce, announceComment, visibility, audioFile, removeAudio]);

  useEffect(() => {
    if (isNaN(novelId) || isNaN(episodeId)) return;
    api.getEpisode(novelId, episodeId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      const ep = d.episode;
      setTitle(ep.title);
      setSummary(ep.summary || "");
      setComment(ep.comment || "");
      setContent(ep.content || "");
      setIsPublished(ep.is_published);
      setNovelTitle(d.novel.title);
      setAudioUrl(ep.audio_url || "");
      setPageMode(ep.page_mode || false);
      setViewMode((ep.view_mode as "text" | "comic") || "text");
      setComicViewMode((ep.comic_view_mode as "paged" | "scroll") || "paged");
      setImageUrls(ep.image_urls || []);
      setReadingDirection((ep.reading_direction as "ltr" | "rtl") || "ltr");
      lastSavedContentRef.current = JSON.stringify({ title: ep.title, summary: ep.summary || "", content: ep.content || "", comment: ep.comment || "", isPublished: ep.is_published, announce: false, announceComment: "", visibility: "public" });
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
    const currentContent = JSON.stringify({ title, summary, content, comment, isPublished, announce, announceComment, visibility });
    if (currentContent === lastSavedContentRef.current) return;
    setSaving(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("summary", summary);
      form.append("content", content);
      form.append("comment", comment);
      form.append("is_published", String(isPublished));
      form.append("page_mode", String(pageMode));
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
        lastSavedContentRef.current = currentContent;
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
    lastSavedContentRef.current = JSON.stringify({ title: d.title, summary: d.summary, content: d.content, comment: d.comment, isPublished: d.is_published, announce: d.announce, announceComment: d.announce_comment, visibility: d.visibility || "public" });
    setShowDraftList(false);
  };

  const deleteDraft = async (id: number) => {
    await fetch(`/api/series/${novelId}/drafts/${id}/delete`, { method: "POST", credentials: "include" });
    loadDrafts();
  };

  const handleAudioChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 20 * 1024 * 1024) { alert("오디오 파일은 20MB 이하만 업로드 가능합니다."); e.target.value = ""; return; }
    if (audioPreview) URL.revokeObjectURL(audioPreview);
    setAudioFile(f);
    setAudioPreview(URL.createObjectURL(f));
  };

  const handleImageAdd = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setImageFiles((prev) => [...prev, ...files]);
    const newPreviews = files.map((f) => URL.createObjectURL(f));
    setImageUrls((prev) => [...prev, ...newPreviews]);
    e.target.value = "";
  };

  const handleImageRemove = (idx: number) => {
    setImageUrls((prev) => prev.filter((_, i) => i !== idx));
    setImageFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleImageMove = (idx: number, dir: -1 | 1) => {
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= imageUrls.length) return;
    setImageUrls((prev) => { const n = [...prev]; [n[idx], n[newIdx]] = [n[newIdx], n[idx]]; return n; });
    setImageFiles((prev) => { const n = [...prev]; [n[idx], n[newIdx]] = [n[newIdx], n[idx]]; return n; });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanContent = (content || "").replace(/<[^>]*>/g, "").trim();
    if (!title.trim() || submitting) return;
    if (viewMode === "text" && !cleanContent) return;
    if (viewMode === "comic" && imageUrls.length === 0) return;
    if (audioFile && audioFile.size > 20 * 1024 * 1024) { alert("오디오 파일은 20MB 이하만 업로드 가능합니다."); return; }
    setSubmitting(true);
    try {
      let uploadedUrls: string[] = [];
      if (viewMode === "comic" && imageFiles.length > 0) {
        setUploadingImages(true);
        for (const f of imageFiles) {
          const fd = new FormData();
          fd.append("file", f);
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 30000);
          const r = await fetch("/api/media/upload", { method: "POST", credentials: "include", body: fd, signal: controller.signal });
          clearTimeout(timeout);
          if (r.ok) { const d = await r.json(); uploadedUrls.push(d.url); }
        }
        setUploadingImages(false);
      } else if (viewMode === "comic") {
        uploadedUrls = imageUrls.filter((u) => !u.startsWith("blob:"));
      }
      const form = new FormData();
      form.append("title", title);
      form.append("content", content);
      form.append("summary", summary);
      form.append("comment", comment);
      form.append("is_published", isPublished ? "true" : "false");
      form.append("page_mode", pageMode ? "true" : "false");
      form.append("view_mode", viewMode);
      form.append("comic_view_mode", comicViewMode);
      form.append("image_urls", JSON.stringify(uploadedUrls));
      form.append("reading_direction", readingDirection);
      if (audioFile) form.append("audio", audioFile);
      else if (removeAudio) form.append("remove_audio", "true");
      if (announce) {
        form.append("announce", "true");
        form.append("announce_comment", announceComment);
      }
      form.append("visibility", visibility);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 60000);
      const res = await fetch(`/api/series/${params.id}/episodes/${params.eid}/edit`, { method: "POST", credentials: "include", body: form, signal: controller.signal });
      clearTimeout(timeout);
      if (res.ok) {
        if (draftId) await fetch(`/api/series/${novelId}/drafts/${draftId}/delete`, { method: "POST", credentials: "include" });
        setDirty(false);
        suppress();
        router.push(`/series/${params.id}/episodes/${params.eid}`);
      } else alert("저장 실패");
    } catch (err) {
      if ((err as any)?.name === "AbortError") alert("요청 시간이 초과되었습니다. 파일 크기를 줄이거나 다시 시도해주세요.");
      else alert("저장 실패");
    }
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
          <div className="episode-view-mode-toggle">
            <button type="button" className={`episode-view-mode-btn ${viewMode === "text" ? "active" : ""}`} onClick={() => { if (viewMode === "comic" && imageUrls.length > 0 && !confirm("전환하면 이미지가 초기화됩니다. 계속하시겠습니까?")) return; setViewMode("text"); }}>글 모드</button>
            <button type="button" className={`episode-view-mode-btn ${viewMode === "comic" ? "active" : ""}`} onClick={() => { if (viewMode === "text" && content.replace(/<[^>]*>/g, "").trim() && !confirm("전환하면 텍스트가 초기화됩니다. 계속하시겠습니까?")) return; setViewMode("comic"); setContent(""); }}>만화 모드</button>
          </div>
          {viewMode === "text" ? (
            <EpisodeEditor value={content} onChange={(v) => setContent(v)} pageMode={pageMode} onPageModeChange={setPageMode} />
          ) : (
            <div className="episode-comic-uploader">
              {imageUrls.map((url, i) => (
                <div key={i} className="episode-comic-img-item">
                  <img src={url} alt={`이미지 ${i + 1}`} />
                  <div className="episode-comic-img-actions">
                    <button type="button" onClick={() => handleImageMove(i, -1)} disabled={i === 0} title="앞으로">‹</button>
                    <span>{i + 1}</span>
                    <button type="button" onClick={() => handleImageMove(i, 1)} disabled={i === imageUrls.length - 1} title="뒤로">›</button>
                    <button type="button" onClick={() => handleImageRemove(i)} title="제거" style={{ color: "var(--danger)" }}>×</button>
                  </div>
                </div>
              ))}
              <label className="episode-comic-add-btn">
                <Icon name="image" /> 이미지 추가
                <input type="file" accept="image/*" multiple onChange={handleImageAdd} style={{ display: "none" }} />
              </label>
              {uploadingImages && <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>이미지 업로드 중...</p>}
              <div className="episode-comic-mode-select" style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>보기 방식:</span>
                <button type="button" className={`episode-view-mode-btn ${comicViewMode === "paged" ? "active" : ""}`} onClick={() => setComicViewMode("paged")}>페이지</button>
                <button type="button" className={`episode-view-mode-btn ${comicViewMode === "scroll" ? "active" : ""}`} onClick={() => setComicViewMode("scroll")}>스크롤</button>
                {comicViewMode === "paged" && (
                  <>
                    <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 8 }}>넘김 방향:</span>
                    <button type="button" className={`episode-view-mode-btn ${readingDirection === "ltr" ? "active" : ""}`} onClick={() => setReadingDirection("ltr")}>좌철</button>
                    <button type="button" className={`episode-view-mode-btn ${readingDirection === "rtl" ? "active" : ""}`} onClick={() => setReadingDirection("rtl")}>우철</button>
                  </>
                )}
              </div>
            </div>
          )}
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
            {audioUrl && !audioFile && !removeAudio && <button type="button" onClick={() => setRemoveAudio(true)} style={{ color: "var(--danger)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>제거</button>}
          </div>
          {audioPreview ? (
            <AudioPlayer src={audioPreview} />
          ) : audioUrl && !removeAudio ? (
            <AudioPlayer src={audioUrl} />
          ) : null}
          <p className="form-help">에피소드 본문 위에 음악 플레이어가 표시됩니다 (MP3, M4A, WAV, FLAC 등)</p>
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
          <button type="submit" disabled={submitting || !title.trim() || (viewMode === "text" && !(content || "").trim()) || (viewMode === "comic" && imageUrls.length === 0)} className="btn btn-primary">저장</button>
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
