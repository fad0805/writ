"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { api, NovelData, EpisodeData } from "@/lib/api";
import Icon from "@/components/Icon";
import ShareButton from "@/components/ShareButton";
import Link from "next/link";

export default function EpisodeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [episode, setEpisode] = useState<EpisodeData | null>(null);
  const [prevEp, setPrevEp] = useState<EpisodeData | null>(null);
  const [nextEp, setNextEp] = useState<EpisodeData | null>(null);
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getEpisode(Number(params.id), Number(params.eid))
      .then((d) => {
        setNovel(d.novel);
        setEpisode(d.episode);
        setPrevEp(d.prev_episode);
        setNextEp(d.next_episode);
        setIsMine(d.is_mine);
        setLoading(false);
      })
      .catch((err) => { setError(err.message || "불러오기 실패"); setLoading(false); });
  }, [params.id, params.eid, router]);

  const handleDelete = async () => {
    if (!confirm("정말 삭제하시겠습니까?")) return;
    try {
      const res = await fetch(`/api/novels/${params.id}/episodes/${params.eid}/delete`, { method: "POST", credentials: "include" });
      if (res.ok) router.push(`/series/${params.id}`);
    } catch {}
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;
  if (error) return <p className="empty-state">오류: {error}</p>;
  if (!novel || !episode) return <p className="empty-state">에피소드를 찾을 수 없습니다.</p>;

  return (
    <>
      <article className="episode-content">
        <div className="episode-header-row">
          <h2>제 {episode.episode_number}화: {episode.title}</h2>
          <div className="episode-header-btns">
            <ShareButton url={`/series/${novel.id}/episodes/${episode.id}`} />
            {isMine && (
              <>
                <button className="btn btn-primary btn-small" onClick={() => router.push(`/series/${novel.id}/episodes/new`)}>새 에피소드</button>
                <button className="btn btn-small" onClick={() => router.push(`/series/${novel.id}/episodes/${episode.id}/edit`)}>편집</button>
                <button className="btn btn-small btn-danger" onClick={handleDelete}>삭제</button>
              </>
            )}
          </div>
        </div>
        <div className="episode-meta episode-meta-bottom">
          <span><Icon name="eye" /> {episode.views}</span>
          <span>{episode.created_at ? new Date(episode.created_at).toLocaleString("ko-KR") : ""}</span>
          <span><Icon name={episode.is_published ? "check" : "lock"} /> {episode.is_published ? "공개" : "비공개"}</span>
        </div>
        {episode.summary && <blockquote className="episode-summary">{episode.summary}</blockquote>}
        <div className="episode-body" dangerouslySetInnerHTML={{ __html: episode.content }} />
        {episode.comment && <div className="episode-comment" dangerouslySetInnerHTML={{ __html: episode.comment }} />}
        <div className="episode-footer">
        <div className="episode-navigation" style={{ margin: 0 }}>
          {prevEp && (
            <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${prevEp.id}`)}>
              ← 제{prevEp.episode_number}화 ({prevEp.title})
            </button>
          )}
          <Link href={`/series/${novel.id}`} className="btn btn-outline">목차</Link>
          {nextEp && (
            <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${nextEp.id}`)}>
              제{nextEp.episode_number}화 ({nextEp.title}) →
            </button>
          )}
        </div>
        </div>
      </article>
    </>
  );
}
