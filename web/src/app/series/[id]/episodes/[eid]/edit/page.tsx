"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import EpisodeEditor from "@/components/EpisodeEditor";
import VisibilitySelector from "@/components/VisibilitySelector";

export default function EditEpisodePage() {
  const params = useParams();
  const router = useRouter();
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

  useEffect(() => {
    const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
    const episodeId = Number(Array.isArray(params.eid) ? params.eid[0] : params.eid);
    if (isNaN(novelId) || isNaN(episodeId)) return;
    api.getNovel(novelId).then((d) => {
      const ep = d.episodes.find((e) => e.id === episodeId);
      if (!ep || !d.is_mine) { router.push(`/series/${novelId}`); return; }
      setTitle(ep.title);
      setSummary(ep.summary);
      setComment(ep.comment || "");
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
      form.append("comment", comment);
      form.append("is_published", isPublished ? "true" : "");
      if (announce) {
        form.append("announce", "true");
        form.append("announce_comment", announceComment);
      }
      form.append("visibility", visibility);
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
          <label>작가 코멘트</label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="이 에피소드에 대한 작가의 코멘트 (선택사항)" />
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
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
