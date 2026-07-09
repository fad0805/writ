"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";

export default function NewNoticePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);

  useEffect(() => {
    if (isNaN(novelId)) return;
    api.getNovel(novelId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      setNovelTitle(d.novel.title);
    }).catch(() => router.push("/series"));
  }, [params.id, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !content.trim() || submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("content", content);
      const res = await fetch(`/api/series/${novelId}/notices/new`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/series/${novelId}/notices`);
      else alert("게시 실패");
    } catch { alert("게시 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <a href={`/series/${novelId}/notices`} className="btn btn-outline btn-small" style={{ marginBottom: 8 }}>← 공지 목록</a>
        <h2 style={{ margin: "8px 0 0" }}>{novelTitle || "로딩 중..."} — 새 공지</h2>
      </div>
      <form onSubmit={handleSubmit} className="episode-form">
        <div className="form-group">
          <label>제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="공지 제목" />
        </div>
        <div className="form-group">
          <label>내용 *</label>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} required rows={10} placeholder="공지 내용" style={{ width: "100%", resize: "vertical" }}></textarea>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">게시</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
