"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import EpisodeEditor from "@/components/EpisodeEditor";

export default function EditEpisodePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [content, setContent] = useState("");
  const [isPublished, setIsPublished] = useState(true);
  const [novelTitle, setNovelTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.getNovel(Number(params.id)).then((d) => {
      const ep = d.episodes.find((e) => e.id === Number(params.eid));
      if (!ep || !d.is_mine) { router.push(`/series/${params.id}`); return; }
      setTitle(ep.title);
      setSummary(ep.summary);
      setContent(ep.content);
      setIsPublished(ep.is_published);
      setNovelTitle(d.novel.title);
      setLoading(false);
    }).catch(() => router.push("/series"));
  }, [params.id, params.eid, router]);

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
      form.append("is_published", isPublished ? "true" : "");
      const res = await fetch(`/api/novels/${params.id}/episodes/${params.eid}/edit`, { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/series/${params.id}/episodes/${params.eid}`);
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
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
          <EpisodeEditor value={content} onChange={(v) => setContent(v)} />
        </div>
        <div className="form-group">
          <label>
            <input type="checkbox" checked={isPublished} onChange={(e) => setIsPublished(e.target.checked)} />
            {" "}공개
          </label>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
