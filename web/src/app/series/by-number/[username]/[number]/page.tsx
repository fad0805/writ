"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NovelData, EpisodeData, User } from "@/lib/api";
import Icon from "@/components/Icon";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";

export default function NovelByNumberPage() {
  const params = useParams();
  const router = useRouter();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeData[]>([]);
  const [author, setAuthor] = useState<User | null>(null);
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/by-series-number/${params.username}/${params.number}`, { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        if (!d.id) { setLoading(false); return; }
        api.getNovel(d.id).then((nd) => {
          setNovel(nd.novel); setEpisodes(nd.episodes);
          setAuthor(nd.author); setIsMine(nd.is_mine); setLoading(false);
        }).catch(() => setLoading(false));
      }).catch(() => setLoading(false));
  }, [params.username, params.number]);

  const handleDelete = async () => {
    if (!confirm("정말 삭제하시겠습니까?")) return;
    try {
      const res = await fetch(`/api/novels/${novel?.id}/delete`, { method: "POST", credentials: "include" });
      if (res.ok) router.push("/series/my");
    } catch {}
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;
  if (!novel) return <p className="empty-state">시리즈를 찾을 수 없습니다.</p>;

  return (
    <>
      <div className="novel-header">
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
          <div style={{ width: 120, aspectRatio: "3/4", borderRadius: 8, flexShrink: 0, overflow: "hidden" }}>
            {novel.cover_image ? (
              <img src={novel.cover_image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", backgroundColor: hashColor(novel.title), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "2em", fontWeight: "bold" }}>
                <Icon name="book" size={36} />
              </div>
            )}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <h2>{novel.title}</h2>
                <p className="novel-author">
                  by <Link href={`/@${author?.username}`}>{author?.display_name || author?.username}</Link>
                </p>
              </div>
              {isMine && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn btn-small" onClick={() => router.push(`/series/${novel.id}/edit`)}>시리즈 편집</button>
                  <button className="btn btn-primary btn-small" onClick={() => router.push(`/series/${novel.id}/episodes/new`)}>새 에피소드</button>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="novel-status">
          <span><Icon name={novel.is_completed ? "check" : "edit"} /> {novel.is_completed ? "완결" : "연재중"}</span>
          <span><Icon name="book" /> 총 {novel.episode_count}화</span>
          <span><Icon name="eye" /> 총 {novel.total_views}회 조회</span>
          <span><Icon name="eye" /> {novel.visibility === "public" ? "전체공개" : novel.visibility === "unlisted" ? "공개" : "비공개"}</span>
        </div>
        {novel.description && <p className="novel-description">{novel.description}</p>}
        {novel.tags && <p className="novel-tags"><Icon name="tag" /> {novel.tags.split(/[ ,]+/).filter(Boolean).map((t, i) => <span key={i} style={{ marginRight: 6 }}>{t}</span>)}</p>}
      </div>

      <div className="episode-list">
        <h3>목차</h3>
        {episodes.length === 0 ? (
          <p className="empty-state">아직 에피소드가 없습니다.</p>
        ) : episodes.map((e) => (
          <div key={e.id} className="episode-item" onClick={() => router.push(`/series/${novel.id}/episodes/${e.id}`)}>
            <div className="episode-number">제 {e.episode_number}화</div>
            <div className="episode-info">
              <span className="episode-title">{e.title}</span>
              <div className="episode-meta">
                <span><Icon name="eye" /> {e.views}</span>
                <span>{e.created_at ? new Date(e.created_at).toISOString().slice(0, 10) : ""}</span>
              </div>
            </div>
            {isMine && (
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto", flexShrink: 0 }}>
                <button className="action-btn" onClick={(ev) => { ev.stopPropagation(); router.push(`/series/${novel.id}/episodes/${e.id}/edit`); }}>
                  <Icon name="edit" />
                </button>
                <button className="action-btn" style={{ color: "var(--text-muted)" }} onClick={async (ev) => {
                  ev.stopPropagation();
                  if (!confirm("정말 삭제하시겠습니까?")) return;
                  try { await fetch(`/api/novels/${novel.id}/episodes/${e.id}/delete`, { method: "POST", credentials: "include" }); window.location.reload(); } catch {}
                }}>
                  <Icon name="trash" />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
