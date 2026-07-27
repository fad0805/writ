"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { api, NoticeData } from "@/lib/api";
import { useBeforeUnload } from "@/lib/useBeforeUnload";
import EpisodeEditor from "@/components/EpisodeEditor";

export default function EditNoticePage() {
  const params = useParams();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [novelTitle, setNovelTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const loadedRef = useRef(false);
  useBeforeUnload(dirty);
  useEffect(() => { if (!loading) loadedRef.current = true; }, [loading]);
  useEffect(() => { if (loadedRef.current) setDirty(true); }, [title, content]);

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
      if (res.ok) { setDirty(false); setTimeout(() => router.push(`/series/${novelId}/notices`), 0); }
      else alert("수정 실패");
    } catch { alert("수정 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <a href={`/series/${novelId}/notices`} className="btn btn-outline btn-small" style={{ marginBottom: 8 }}>← 공지 목록</a>
        <h2 style={{ margin: "8px 0 0" }}>{novelTitle || "로딩 중..."} — 공지 편집</h2>
      </div>
      <form onSubmit={handleSubmit} className="episode-form">
        <div className="form-group">
          <label>제목</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="공지 제목" />
        </div>
        <div className="form-group">
          <label>내용 *</label>
          <EpisodeEditor value={content} onChange={(v) => setContent(v)} />
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting || !title.trim() || !content.trim()} className="btn btn-primary">수정</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
