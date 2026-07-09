"use client";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { useBeforeUnload } from "@/lib/useBeforeUnload";
import TextareaHighlight from "@/components/TextareaHighlight";
import TagInput from "@/components/TagInput";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";
import SeriesStatusSelector from "@/components/SeriesStatusSelector";
import ImageCropper from "@/components/ImageCropper";

function makeBlob(file: Blob): string {
  return URL.createObjectURL(file);
}

export default function EditNovelPage() {
  const params = useParams();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [coverImageUrl, setCoverImageUrl] = useState("");
  const [removeCover, setRemoveCover] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState("");
  const [cropSrc, setCropSrc] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [seriesStatus, setSeriesStatus] = useState("ongoing");
  const [coverSensitive, setCoverSensitive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [dirty, setDirty] = useState(false);

  const loadedRef = useRef(false);
  useBeforeUnload(dirty);
  useEffect(() => { if (!loading) loadedRef.current = true; }, [loading]);
  useEffect(() => { if (loadedRef.current) setDirty(true); }, [title, description, tags, visibility, seriesStatus, coverSensitive, imageFile, removeCover]);

  const revokeBlobs = useCallback(() => {
    if (coverPreview) URL.revokeObjectURL(coverPreview);
  }, [coverPreview]);

  useEffect(() => {
    const id = Number(Array.isArray(params.id) ? params.id[0] : params.id);
    if (isNaN(id)) return;
    api.getNovel(id)
      .then((d) => {
        if (!d.is_mine) { router.push(`/series/${id}`); return; }
        setTitle(d.novel.title);
        setDescription(d.novel.description);
        setTags(d.novel.tags);
        setVisibility(d.novel.visibility || "public");
        setCoverImageUrl(d.novel.cover_image || "");
        setSeriesStatus(d.novel.status || "ongoing");
        setCoverSensitive((d.novel as any).is_sensitive || false);
        setLoading(false);
      })
      .catch(() => router.push("/series"));
  }, [params.id, router]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    revokeBlobs();
    setImageFile(f);
    setCoverPreview(makeBlob(f));
    setCropSrc(makeBlob(f));
  };

  const handleCrop = useCallback((blob: Blob) => {
    revokeBlobs();
    const cropped = new File([blob], imageFile?.name || "cover.jpg", { type: "image/jpeg" });
    setImageFile(cropped);
    setCoverPreview(makeBlob(blob));
    setCropSrc("");
  }, [imageFile, revokeBlobs]);

  const handleCropClose = useCallback(() => {
    setCropSrc("");
    if (!imageFile) setCoverPreview("");
  }, [imageFile]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("description", description);
      form.append("tags", tags);
      form.append("visibility", visibility);
      form.append("status", seriesStatus);
      form.append("is_sensitive", coverSensitive ? "true" : "");
      if (imageFile) form.append("cover_image", imageFile);
      else if (removeCover) form.append("remove_cover", "true");
      const res = await fetch(`/api/series/${params.id}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) { setDirty(false); router.push(`/series/${params.id}`); }
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  const showPreview = coverPreview || coverImageUrl;

  return (
    <>
      <h2>시리즈 편집</h2>
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="form-group">
          <label>설명</label>
          <TextareaHighlight value={description} onChange={(v) => setDescription(v)} placeholder="" maxLength={500} cwLength={0} rows={4} />
          <div className="char-count">{description.length}/{500}</div>
        </div>
        <div className="form-group">
          <label>태그 <span className="font-normal text-dim text-sm" style={{ marginLeft: 6 }}>최대 10개</span></label>
          <TagInput value={tags} onChange={(v) => setTags(v)} />
        </div>
        <div className="form-group">
          <label>표지 이미지</label>
          <div className="profile-edit-avatar-wrap">
            {showPreview && <img src={showPreview} alt="" className="cover-preview" style={coverSensitive ? { filter: "blur(12px)" } : undefined} />}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
              {showPreview && (
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, color: "var(--text-secondary)" }}>
                  <input type="checkbox" checked={coverSensitive} onChange={(e) => setCoverSensitive(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
                  표지 민감 처리
                </label>
              )}
              {showPreview && <p className="form-help" style={{ margin: 0 }}>켜면 시리즈 표지가 블러 처리되어 표시됩니다.</p>}
              <div className="profile-edit-file-row">
                <label className="btn btn-outline profile-edit-file-label" style={{ cursor: "pointer" }}>
                  파일 선택
                  <input type="file" ref={inputRef} accept="image/*" onChange={handleFileChange} style={{ display: "none" }} />
                </label>
                {imageFile && <span className="profile-edit-file-name">{imageFile.name}</span>}
                {showPreview && !removeCover && <button type="button" onClick={() => { setRemoveCover(true); setImageFile(null); }} style={{ color: "var(--danger)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}>제거</button>}
              </div>
            </div>
          </div>
        </div>
        <div className="form-group">
          <label>공개 설정</label>
          <SeriesVisibilitySelector value={visibility} onChange={(v) => setVisibility(v)} />
          <p className="form-help">전체공개는 모든 시리즈 목록에 노출되고, 공개는 작가 프로필과 URL로만 접근할 수 있습니다.</p>
        </div>
        <div className="form-group">
          <label>연재 상태</label>
          <SeriesStatusSelector value={seriesStatus} onChange={(v) => setSeriesStatus(v)} />
        </div>
        <div className="form-actions form-actions-between">
          <button
            type="button"
            className="form-delete-btn"
            onClick={async () => {
              if (!confirm("정말 삭제하시겠습니까?")) return;
              try {
                const res = await fetch(`/api/series/${params.id}/delete`, { method: "POST", credentials: "include" });
                if (res.ok) { window.dispatchEvent(new Event("novelchange")); router.push("/series/my"); }
              } catch {}
            }}
          >
            삭제
          </button>
          <div className="form-btn-row">
            <button type="submit" disabled={submitting || !title.trim()} className="btn btn-primary">저장</button>
            <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
          </div>
        </div>
      </form>
      {cropSrc && <ImageCropper src={cropSrc} onCrop={handleCrop} onClose={handleCropClose} aspectRatio={3 / 4} />}
    </>
  );
}
