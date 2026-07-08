"use client";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState, useEffect } from "react";
import { api } from "@/lib/api";
import TextareaHighlight from "@/components/TextareaHighlight";
import TagInput from "@/components/TagInput";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";

export default function EditNovelPage() {
  const params = useParams();
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [coverImage, setCoverImage] = useState("");
  const [coverPreview, setCoverPreview] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [isCompleted, setIsCompleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

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
        setCoverImage(d.novel.cover_image || "");
        setIsCompleted(d.novel.is_completed);
        setLoading(false);
      })
      .catch(() => router.push("/series"));
  }, [params.id, router]);

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
      if (fileRef.current?.files?.[0]) form.append("cover_image", fileRef.current.files[0]);
      const res = await fetch(`/api/novels/${params.id}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/series/${params.id}`);
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

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
          <input type="file" ref={fileRef} accept="image/*" onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setCoverPreview(URL.createObjectURL(f));
          }} />
          {(coverPreview || coverImage) && <img src={coverPreview || coverImage} alt="" className="cover-preview" />}
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
                const res = await fetch(`/api/novels/${params.id}/delete`, { method: "POST", credentials: "include" });
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
    </>
  );
}
