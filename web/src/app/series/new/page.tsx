"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Icon from "@/components/Icon";
import TextareaHighlight from "@/components/TextareaHighlight";
import TagInput from "@/components/TagInput";
import Link from "next/link";

export default function NewNovelPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [coverImage, setCoverImage] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [submitting, setSubmitting] = useState(false);

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
      if (coverImage) form.append("cover_image", coverImage);
      const res = await fetch("/api/novels/new", { method: "POST", credentials: "include", body: form });
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
          <label>표지 이미지 URL</label>
          <input type="text" value={coverImage} onChange={(e) => setCoverImage(e.target.value)} placeholder="https://..." />
          {coverImage && <img src={coverImage} alt="" style={{ width: "100%", maxHeight: 200, objectFit: "cover", borderRadius: 8, marginTop: 6 }} />}
        </div>
        <div className="form-group">
          <label>공개 설정</label>
          <div className="visibility-selector" style={{ fontSize: "0.82em" }}>
            {[
              { value: "public", label: "전체공개", icon: "globe" },
              { value: "unlisted", label: "공개", icon: "eye" },
              { value: "private", label: "비공개", icon: "lock" },
            ].map((v) => (
              <label key={v.value}>
                <input type="radio" name="visibility" value={v.value} checked={visibility === v.value} onChange={() => setVisibility(v.value)} />
                <Icon name={v.icon} /> {v.label}
              </label>
            ))}
          </div>
          <p className="form-help">전체공개는 모든 시리즈 목록에 노출되고, 공개는 작가 프로필과 URL로만 접근할 수 있습니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting || !title.trim()} className="btn btn-primary">만들기</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
