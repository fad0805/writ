"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NoticeData, NovelData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";
import { sanitizePost } from "@/lib/sanitize";

export default function NoticeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [notice, setNotice] = useState<NoticeData | null>(null);
  const { user } = useAuth();
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);

  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);
  const noticeId = Number(Array.isArray(params.nid) ? params.nid[0] : params.nid);

  useEffect(() => {
    if (isNaN(novelId) || isNaN(noticeId)) return;
    api.getNovel(novelId).then((d) => {
      setNovel(d.novel);
      setIsMine(d.is_mine);
    }).catch(() => {});
    fetch(`/api/series/${novelId}/notices`, { credentials: "include" })
      .then((r) => r.json())
      .then((list) => {
        const found = list.find((n: NoticeData) => n.id === noticeId);
        if (found) setNotice(found);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [params.id, params.nid]);

  if (loading) return <p className="empty-state">로딩 중...</p>;
  if (!notice) return <p className="empty-state">공지를 찾을 수 없습니다.</p>;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <a href={`/series/${novelId}`} className="btn btn-outline btn-small" style={{ marginBottom: 8 }}>← 작품으로 돌아가기</a>
        <h2 style={{ margin: "8px 0 0" }}>{novel?.title || "시리즈"} — 공지사항</h2>
      </div>
      <div className="notice-detail">
        <h3>{notice.is_pinned && <span style={{ color: "var(--danger)", marginRight: 6 }}><Icon name="pin_filled" /></span>}{notice.title}</h3>
        <p className="text-secondary" style={{ fontSize: "0.85em", marginBottom: 16 }}>
          {notice.created_at ? new Date(notice.created_at).toISOString().slice(0, 10) : ""}
        </p>
        <div className="notice-content" dangerouslySetInnerHTML={{ __html: sanitizePost(notice.content) }}></div>
        {(isMine || user?.role === "admin" || user?.role === "moderator" || user?.role === "owner") && (
          <div className="form-actions" style={{ marginTop: 24 }}>
            {isMine && <Link href={`/series/${novelId}/notices/${noticeId}/edit`} className="btn">편집</Link>}
            <button type="button" onClick={async () => {
              if (!confirm(`공지 "${notice.title}"를 삭제하시겠습니까?`)) return;
              try {
                await fetch(`/api/series/${novelId}/notices/${noticeId}/delete`, { method: "POST", credentials: "include" });
                router.push(`/series/${novelId}/notices`);
              } catch {}
            }} className="btn" style={{ color: "var(--danger)" }}>삭제</button>
            <button type="button" onClick={() => router.push(`/series/${novelId}/notices`)} className="btn btn-outline">공지 목록</button>
          </div>
        )}
        {!isMine && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner" && (
          <div className="form-actions" style={{ marginTop: 24 }}>
            <button type="button" onClick={() => router.push(`/series/${novelId}/notices`)} className="btn btn-outline">공지 목록</button>
          </div>
        )}
      </div>
    </>
  );
}
