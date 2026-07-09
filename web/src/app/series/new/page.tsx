"use client";
import { useRouter } from "next/navigation";
import { useState, useRef, useCallback } from "react";
import TextareaHighlight from "@/components/TextareaHighlight";
import TagInput from "@/components/TagInput";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";
import SeriesStatusSelector from "@/components/SeriesStatusSelector";
import ImageCropper from "@/components/ImageCropper";

function makeBlob(file: Blob): string {
  const url = URL.createObjectURL(file);
  return url;
}

export default function NewNovelPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState("");
  const [cropSrc, setCropSrc] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [seriesStatus, setSeriesStatus] = useState("ongoing");
  const [coverSensitive, setCoverSensitive] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const revokeBlobs = useCallback(() => {
    if (coverPreview) URL.revokeObjectURL(coverPreview);
  }, [coverPreview]);

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
      const res = await fetch("/api/series/new", { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (res.ok) { window.dispatchEvent(new Event("novelchange")); router.push(`/series/${data.novel_id}`); }
      else alert("만들기 실패");
    } catch { alert("만들기 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <h2>새 시리즈</h2>
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
          <label>태그 (최대 10개)</label>
          <TagInput value={tags} onChange={(v) => setTags(v)} />
        </div>
        <div className="form-group">
          <label>표지 이미지</label>
          <div className="profile-edit-avatar-wrap">
            {coverPreview && <img src={coverPreview} alt="" className="cover-preview" style={coverSensitive ? { filter: "blur(12px)" } : undefined} />}
            <div>
              <div className="profile-edit-file-row">
                <label className="btn btn-outline profile-edit-file-label" style={{ cursor: "pointer" }}>
                  파일 선택
                  <input type="file" ref={inputRef} accept="image/*" onChange={handleFileChange} style={{ display: "none" }} />
                </label>
                {imageFile && <span className="profile-edit-file-name">{imageFile.name}</span>}
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, color: "var(--text-secondary)", marginTop: 8 }}>
                <input type="checkbox" checked={coverSensitive} onChange={(e) => setCoverSensitive(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
                표지 민감 처리
              </label>
              <p className="form-help" style={{ fontSize: 12, marginTop: 4 }}>켜면 시리즈 표지가 블러 처리되어 표시됩니다.</p>
            </div>
          </div>
        </div>
        <div className="form-group">
          <label>연재 상태</label>
          <SeriesStatusSelector value={seriesStatus} onChange={(v) => setSeriesStatus(v)} />
        </div>
        <div className="form-group">
          <label>공개 설정</label>
          <SeriesVisibilitySelector value={visibility} onChange={(v) => setVisibility(v)} />
          <p className="form-help">전체공개는 모든 시리즈 목록에 노출되고, 공개는 작가 프로필과 URL로만 접근할 수 있습니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting || !title.trim()} className="btn btn-primary">만들기</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
      {cropSrc && <ImageCropper src={cropSrc} onCrop={handleCrop} onClose={handleCropClose} aspectRatio={3 / 4} />}
    </>
  );
}
