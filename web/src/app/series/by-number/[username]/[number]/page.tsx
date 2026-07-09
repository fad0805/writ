"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NovelData, EpisodeData, NoticeData, User } from "@/lib/api";
import Icon from "@/components/Icon";
import ShareButton from "@/components/ShareButton";
import SharePostModal from "@/components/SharePostModal";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";
import { useAuth } from "@/lib/auth";

export default function NovelByNumberPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeData[]>([]);
  const [author, setAuthor] = useState<User | null>(null);
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pinnedNotices, setPinnedNotices] = useState<NoticeData[]>([]);
  const [showSharePost, setShowSharePost] = useState(false);

  useEffect(() => {
    fetch(`/api/by-series-number/${params.username}/${params.number}`, { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        if (!d.id) { setLoading(false); return; }
        api.getNovel(d.id).then((nd) => {
          setNovel(nd.novel); setEpisodes(nd.episodes);
          setAuthor(nd.author); setIsMine(nd.is_mine); setLoading(false);
          fetch(`/api/series/${d.id}/notices`, { credentials: "include" })
            .then((r) => r.json())
            .then((list) => setPinnedNotices((list as NoticeData[]).filter((n) => n.is_pinned)))
            .catch(() => {});
        }).catch(() => setLoading(false));
      }).catch(() => setLoading(false));
  }, [params.username, params.number]);

  if (loading) return <p className="empty-state">로딩 중...</p>;
  if (!novel) return <p className="empty-state">시리즈를 찾을 수 없습니다.</p>;

  return (
    <>
      <div className="novel-header">
        <div className="series-header-row">
          <div className="cover-wrap-120">
            {novel.cover_image ? (
              <img src={novel.cover_image} alt="" className="cover-img" />
            ) : (
              <div className="cover-fallback cover-fallback-xl" style={{ backgroundColor: hashColor(novel.title) }}>
                <Icon name="book" size={36} />
              </div>
            )}
          </div>
          <div className="series-header-info">
            <div className="series-header-top">
              <div>
                <h2>{novel.title}</h2>
                <p className="novel-author">
                  by <Link href={`/@${author?.username}`}>{author?.display_name || author?.username}</Link>
                </p>
              </div>
              <div className="series-header-btns">
                {novel.visibility !== "private" && <ShareButton url={`/series/by-number/${params.username}/${params.number}`} />}
                {user && <button className="action-btn" onClick={() => setShowSharePost(true)} title="포스트로 공유"><Icon name="edit" /></button>}
                {isMine && (
                  <>
                    <button className="btn btn-small" onClick={() => router.push(`/series/${novel.id}/edit`)}>시리즈 편집</button>
                    <button className="btn btn-primary btn-small" onClick={() => router.push(`/series/${novel.id}/episodes/new`)}>새 에피소드</button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="novel-status">
          <span><Icon name={({ ongoing: "edit", hiatus: "moon", discontinued: "x", completed: "check" } as Record<string,string>)[novel.status] || "edit"} /> {({ ongoing: "연재중", hiatus: "휴재", discontinued: "연재중단", completed: "완결" } as Record<string,string>)[novel.status] || "연재중"}</span>
          <span><Icon name="book" /> 총 {novel.episode_count}화</span>
          {isMine && <span><Icon name="eye" /> 총 {novel.total_views}회 조회</span>}
          <span><Icon name="eye" /> {novel.visibility === "public" ? "전체공개" : novel.visibility === "unlisted" ? "공개" : "비공개"}</span>
        </div>
        {novel.description && <p className="novel-description">{novel.description}</p>}
        {novel.tags && <p className="novel-tags"><Icon name="tag" /> {novel.tags.split(/[ ,]+/).filter(Boolean).map((t, i) => <span key={i} className="tag-spacing">{t}</span>)}</p>}
      </div>

      {pinnedNotices.length > 0 && (
        <div className="pinned-notices">
          {pinnedNotices.map((n) => (
            <div key={n.id} className="pinned-notice-item" onClick={() => router.push(`/series/${novel.id}/notices/${n.id}`)}>
              <span className="pinned-notice-icon">📌</span>
              <span className="pinned-notice-title">{n.title}</span>
              <span className="pinned-notice-date">{n.created_at ? new Date(n.created_at).toISOString().slice(0, 10) : ""}</span>
            </div>
          ))}
        </div>
      )}
      <div className="episode-list">
        <div className="episode-list-header">
          <h3 style={{ margin: 0, border: "none", padding: 0 }}>목차</h3>
          <a href={`/series/${novel.id}/notices`} className="btn btn-small btn-outline" style={{ fontSize: "0.75em" }}>공지사항</a>
        </div>
        {episodes.length === 0 ? (
          <p className="empty-state">아직 에피소드가 없습니다.</p>
        ) : episodes.map((e) => (
          <div key={e.id} className="episode-item" onClick={() => router.push(`/series/${novel.id}/episodes/${e.id}`)}>
            <div className="episode-number">제 {e.episode_number}화</div>
            <div className="episode-info">
              <span className="episode-title">{e.title}</span>
              <div className="episode-meta">
                {isMine && <span><Icon name="eye" /> {e.views}</span>}
                <span>{e.created_at ? new Date(e.created_at).toISOString().slice(0, 10) : ""}</span>
              </div>
            </div>
            {isMine && (
              <div className="episode-actions-row">
                <button className="action-btn" onClick={(ev) => { ev.stopPropagation(); router.push(`/series/${novel.id}/episodes/${e.id}/edit`); }}>
                  <Icon name="edit" />
                </button>
                <button className="action-btn text-muted" onClick={async (ev) => {
                  ev.stopPropagation();
                  if (!confirm("정말 삭제하시겠습니까?")) return;
                  try { await fetch(`/api/series/${novel.id}/episodes/${e.id}/delete`, { method: "POST", credentials: "include" }); window.location.reload(); } catch {}
                }}>
                  <Icon name="trash" />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {showSharePost && <SharePostModal url={`/series/by-number/${params.username}/${params.number}`} title={novel.title} authorName={author?.display_name || author?.username} description={novel.description} tags={novel.tags} onClose={() => setShowSharePost(false)} />}
    </>
  );
}
