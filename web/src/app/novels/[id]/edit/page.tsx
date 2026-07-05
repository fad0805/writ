"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import Link from "next/link";

export default function EditNovelPage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [coverImage, setCoverImage] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [isCompleted, setIsCompleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.getNovel(Number(params.id))
      .then((d) => {
        if (!d.is_mine) { router.push(`/novels/${params.id}`); return; }
        setTitle(d.novel.title);
        setDescription(d.novel.description);
        setTags(d.novel.tags);
        setVisibility(d.novel.visibility || "public");
        setCoverImage(d.novel.cover_image || "");
        setIsCompleted(d.novel.is_completed);
        setLoading(false);
      })
      .catch(() => router.push("/novels"));
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
      if (coverImage) form.append("cover_image", coverImage);
      const res = await fetch(`/api/novels/${params.id}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/novels/${params.id}`);
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
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
        </div>
        <div className="form-group">
          <label>태그</label>
          <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="태그를 입력하고 스페이스를 누르세요" />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
            {tags.split(/[ ,]+/).filter(Boolean).map((t, i) => (
              <span key={i} style={{ padding: "2px 8px", borderRadius: 4, background: "var(--bg-tertiary)", border: "1px solid var(--border)", color: "var(--accent)", fontSize: "0.85em" }}>{t}</span>
            ))}
          </div>
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
        <div className="form-group" style={{ marginLeft: 4 }}>
          <label>
            <input type="checkbox" checked={isCompleted} onChange={(e) => setIsCompleted(e.target.checked)} />
            {" "}완결
          </label>
        </div>
        <div className="form-actions" style={{ justifyContent: "space-between" }}>
          <button
            type="button"
            onClick={async () => {
              if (!confirm("정말 삭제하시겠습니까?")) return;
              try {
                const res = await fetch(`/api/novels/${params.id}/delete`, { method: "POST", credentials: "include" });
                if (res.ok) { window.dispatchEvent(new Event("novelchange")); router.push("/novels/my"); }
              } catch {}
            }}
            style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "0.85em", padding: 0, marginLeft: 4 }}
          >
            삭제
          </button>
          <div style={{ display: "flex", gap: 10 }}>
            <button type="submit" disabled={submitting || !title.trim()} className="btn btn-primary">저장</button>
            <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
          </div>
        </div>
      </form>
    </>
  );
}
