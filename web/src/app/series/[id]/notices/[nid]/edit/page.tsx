"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NoticeData } from "@/lib/api";
import Link from "next/link";

export default function EditNoticePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const noticeId = Number(Array.isArray(params.nid) ? params.nid[0] : params.nid);

  useEffect(() => {
    if (isNaN(novelId) || isNaN(noticeId)) return;
    api.getNovel(novelId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      setNovelTitle(d.novel.title);
    }).catch(() => router.push("/series"));
    fetch(`/api/series/${novelId}/notices`, { credentials: "include" })
      .then((r) => r.json())
      .then((list) => {
        const found = list.find((n: NoticeData) => n.id === noticeId);
        if (found) { setTitle(found.title); setContent(found.content); setLoading(false); }
        else router.push(`/series/${novelId}/notices`);
      })
      .catch(() => router.push(`/series/${novelId}/notices`));
  }, [params.id, params.nid, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !content.trim() || submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("title", title);
      form.append("content", content);
      const res = await fetch(`/api/series/${novelId}/notices/${noticeId}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/series/${novelId}/notices`);
      else alert("수정 실패");
    } catch { alert("수정 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <h2><Link href={`/series/${novelId}`} className="no-underline" style={{ color: "inherit" }}>{novelTitle || "시리즈"}</Link></h2>
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
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">수정</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
