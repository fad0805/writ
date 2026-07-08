"use client";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import TextareaHighlight from "@/components/TextareaHighlight";
import TagInput from "@/components/TagInput";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";
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
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState("");
  const [cropSrc, setCropSrc] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [isCompleted, setIsCompleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

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
        setIsCompleted(d.novel.is_completed);
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
      form.append("is_completed", isCompleted ? "true" : "");
      if (imageFile) form.append("cover_image", imageFile);
      const res = await fetch(`/api/series/${params.id}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/series/${params.id}`);
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
            {showPreview && <img src={showPreview} alt="" className="cover-preview" />}
            <div>
              <div className="profile-edit-file-row">
                <label className="btn btn-outline profile-edit-file-label" style={{ cursor: "pointer" }}>
                  파일 선택
                  <input type="file" ref={inputRef} accept="image/*" onChange={handleFileChange} style={{ display: "none" }} />
                </label>
                {imageFile && <span className="profile-edit-file-name">{imageFile.name}</span>}
              </div>
            </div>
          </div>
        </div>
        <div className="form-group">
          <label>공개 설정</label>
          <SeriesVisibilitySelector value={visibility} onChange={(v) => setVisibility(v)} />
          <p className="form-help">전체공개는 모든 시리즈 목록에 노출되고, 공개는 작가 프로필과 URL로만 접근할 수 있습니다.</p>
        </div>
        <div className="form-group ml-4">
          <label>
            <input type="checkbox" checked={isCompleted} onChange={(e) => setIsCompleted(e.target.checked)} />
            {" "}완결
          </label>
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
