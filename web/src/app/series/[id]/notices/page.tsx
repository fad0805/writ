"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NoticeData, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

export default function NoticesPage() {
  const params = useParams();
  const router = useRouter();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [notices, setNotices] = useState<NoticeData[]>([]);
  const { user } = useAuth();
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);

  const novelId = Number(Array.isArray(params.id) ? params.id[0] : params.id);

  const load = () => {
    if (isNaN(novelId)) return;
    api.getNovel(novelId).then((d) => {
      setNovel(d.novel);
      setIsMine(d.is_mine);
    }).catch(() => router.push("/series"));
    fetch(`/api/series/${novelId}/notices`, { credentials: "include" })
      .then((r) => r.json())
      .then((d) => { setNotices(d); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, [params.id]);

  const togglePin = async (n: NoticeData) => {
    const res = await fetch(`/api/series/${novelId}/notices/${n.id}/pin`, { method: "POST", credentials: "include" });
    if (res.ok) {
      const updated = await res.json();
      setNotices((prev) => prev.map((x) => (x.id === n.id ? updated : x)));
    } else {
      const d = await res.json().catch(() => ({}));
      alert(d.detail || "고정 실패");
    }
  };

  const handleDelete = async (n: NoticeData) => {
    if (!confirm("정말 삭제하시겠습니까?")) return;
    const res = await fetch(`/api/series/${novelId}/notices/${n.id}/delete`, { method: "POST", credentials: "include" });
    if (res.ok) setNotices((prev) => prev.filter((x) => x.id !== n.id));
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <a href={`/series/${novelId}`} className="btn btn-outline btn-small" style={{ marginBottom: 8 }}>← 작품으로 돌아가기</a>
        <h2 style={{ margin: "8px 0 0" }}>{novel?.title || "시리즈"} — 공지사항</h2>
      </div>
      <div className="flex-between" style={{ marginBottom: 16 }}>
        <span />
        {isMine && <Link href={`/series/${novelId}/notices/new`} className="btn btn-primary btn-small">새 공지</Link>}
      </div>
      {notices.length === 0 ? (
        <p className="empty-state">공지사항이 없습니다.</p>
      ) : notices.map((n) => (
        <div key={n.id} className="notice-item">
          <div className="notice-item-top">
            <span className="notice-title" onClick={() => router.push(`/series/${novelId}/notices/${n.id}`)}>
              {n.is_pinned && <span style={{ color: "var(--danger)", marginRight: 6 }}><Icon name="pin_filled" /></span>}
              {n.title}
            </span>
            <span className="notice-date">{n.created_at ? new Date(n.created_at).toISOString().slice(0, 10) : ""}</span>
          </div>
          {(isMine || user?.role === "admin" || user?.role === "moderator" || user?.role === "owner") && (
            <div className="notice-actions">
              {isMine && <button className="action-btn" onClick={() => togglePin(n)} title={n.is_pinned ? "고정 해제" : "고정 (최대 3개)"} style={{ color: n.is_pinned ? "var(--danger)" : undefined }}>
                <Icon name={n.is_pinned ? "pin_filled" : "pin"} />
              </button>}
              {isMine && <button className="action-btn" onClick={() => router.push(`/series/${novelId}/notices/${n.id}/edit`)}><Icon name="edit" /></button>}
              <button className="action-btn text-muted" onClick={() => handleDelete(n)}><Icon name="trash" /></button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
