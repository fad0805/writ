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
  const [content, setContent] = useState("");
  const [announce, setAnnounce] = useState(false);
  const [visibility, setVisibility] = useState("public");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.getNovel(Number(params.id)).then((d) => {
      if (!d.is_mine) { router.push(`/series/${params.id}`); return; }
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
      if (announce) form.append("announce", "true");
      form.append("visibility", visibility);
      const res = await fetch(`/api/novels/${params.id}/episodes/new`, { method: "POST", credentials: "include", body: form });
      const data = await res.json();
      if (res.ok) router.push(`/series/${params.id}/episodes/${data.episode_id}`);
      else alert("게시 실패");
    } catch { alert("게시 실패"); }
    setSubmitting(false);
  };

  return (
    <>
      <h2><Link href={`/series/${params.id}`} style={{ color: "inherit", textDecoration: "none" }}>{novelTitle || "로딩 중..."}</Link></h2>
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
        <div className="form-group announce-group">
          <label>
            <input type="checkbox" checked={announce} onChange={(e) => setAnnounce(e.target.checked)} />
            {" "}SNS에 홍보글 게시 (ActivityPub으로 연동됨)
          </label>
          {announce && (
            <VisibilitySelector value={visibility} onChange={(v) => setVisibility(v)} />
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
