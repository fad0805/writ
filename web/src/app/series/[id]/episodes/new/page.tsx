"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import VisibilitySelector from "@/components/VisibilitySelector";
import EpisodeEditor from "@/components/EpisodeEditor";
import Link from "next/link";

export default function NewEpisodePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [comment, setComment] = useState("");
  const [content, setContent] = useState("");
  const [announce, setAnnounce] = useState(false);
  const [visibility, setVisibility] = useState("public");
  const [announceComment, setAnnounceComment] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
    if (isNaN(novelId)) return;
    api.getNovel(novelId).then((d) => {
      if (!d.is_mine) { router.push(`/series/${novelId}`); return; }
      setNovelTitle(d.novel.title);
    }).catch(() => router.push("/series"));
  }, [params.id, router]);

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
      if (announce) {
        form.append("announce", "true");
        form.append("announce_comment", announceComment);
      }
      form.append("visibility", visibility);
      const res = await fetch(`/api/series/${params.id}/episodes/new`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (res.ok) router.push(`/series/${params.id}/episodes/${data.episode_id}`);
      else alert("게시 실패");
    } catch { alert("게시 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <h2><Link href={`/series/${params.id}`} className="no-underline" style={{ color: "inherit" }}>{novelTitle || "로딩 중..."}</Link></h2>
      <form onSubmit={handleSubmit} className="episode-form">
        <div className="form-group">
          <label>에피소드 제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="에피소드 제목" />
        </div>
        <div className="form-group">
          <label>요약/스포일러 방지</label>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2} placeholder="에피소드 요약 (선택사항)" />
        </div>
        <div className="form-group">
          <label>내용 *</label>
          <EpisodeEditor value={content} onChange={(v) => setContent(v)} />
        </div>
        <div className="form-group">
          <label>작가 코멘트</label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="이 에피소드에 대한 작가의 코멘트 (선택사항)" />
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
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">게시</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
