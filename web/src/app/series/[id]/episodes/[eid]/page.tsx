"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { api, NovelData, EpisodeData } from "@/lib/api";
import Icon from "@/components/Icon";
import ShareButton from "@/components/ShareButton";
import SharePostModal from "@/components/SharePostModal";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { installCodeCopyButtons } from "@/lib/codeCopy";

export default function EpisodeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [episode, setEpisode] = useState<EpisodeData | null>(null);
  const [prevEp, setPrevEp] = useState<EpisodeData | null>(null);
  const [nextEp, setNextEp] = useState<EpisodeData | null>(null);
  const [isMine, setIsMine] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showSharePost, setShowSharePost] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [reportReason, setReportReason] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(false);
  const [reportRules, setReportRules] = useState<any[]>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<number[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (bodyRef.current) installCodeCopyButtons(bodyRef.current);
  }, [episode]);

  const handleDelete = async () => {
    if (!confirm("정말 삭제하시겠습니까?")) return;
    try {
      const res = await fetch(`/api/series/${params.id}/episodes/${params.eid}/delete`, { method: "POST", credentials: "include" });
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
            {novel?.visibility !== "private" && <ShareButton url={`/series/${novel.id}/episodes/${episode.id}`} />}
            {user && <button className="action-btn" onClick={() => setShowSharePost(true)} title="포스트로 공유"><Icon name="edit" /></button>}
            {user && !isMine && (
              <button className="action-btn" onClick={() => { setShowReport(true); setReportReason(""); setReportError(""); setReportDone(false); setSelectedRuleIds([]); fetch("/api/rules").then((r) => r.json()).then((d) => setReportRules(d)).catch(() => {}); }} title="신고">
                <Icon name="flag" />
              </button>
            )}
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
          {isMine && episode.views !== undefined && <span><Icon name="eye" /> {episode.views}</span>}
          <span>{episode.created_at ? new Date(episode.created_at).toLocaleString("ko-KR") : ""}</span>
          <span><Icon name={episode.is_published ? "check" : "lock"} /> {episode.is_published ? "공개" : "비공개"}</span>
        </div>
        {!episode.is_published && !isMine ? (
          <div className="empty-state" style={{ padding: "40px 0" }}>비공개 에피소드입니다</div>
        ) : (
          <>
            {episode.summary && <blockquote className="episode-summary">{episode.summary}</blockquote>}
            <div ref={bodyRef} className="episode-body" dangerouslySetInnerHTML={{ __html: episode.content }} />
            {episode.comment && <div className="episode-comment" dangerouslySetInnerHTML={{ __html: episode.comment }} />}
          </>
        )}
        <div className="episode-footer">
        <div className="episode-nav">
          <div className="episode-nav-side">
            {prevEp ? (
              <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${prevEp.id}`)}>
                ← 제 {prevEp.episode_number} 화 ({prevEp.title})
              </button>
            ) : (
              <span className="episode-nav-none">이전 화가 없습니다</span>
            )}
          </div>
          <Link href={`/series/${novel.id}`} className="btn btn-outline">목차</Link>
          <div className="episode-nav-side">
            {nextEp ? (
              <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${nextEp.id}`)}>
                제 {nextEp.episode_number} 화 ({nextEp.title}) →
              </button>
            ) : (
              <span className="episode-nav-none">다음 화가 없습니다</span>
            )}
          </div>
        </div>
        </div>
      </article>
      {showSharePost && <SharePostModal url={`/series/${novel.id}/episodes/${episode.id}`} content={`「${episode.episode_number}화: ${episode.title}」\n${novel.title} by ${novel.author?.display_name || novel.author?.username}`} onClose={() => setShowSharePost(false)} />}
      {showReport && (
        <div className="reply-modal-backdrop active" onClick={() => setShowReport(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <button className="reply-modal-close" onClick={() => setShowReport(false)}>×</button>
            <h3>에피소드 신고</h3>
            {reportDone ? (
              <p style={{ color: "var(--text-secondary)", margin: "16px 0" }}>신고가 접수되었습니다. 검토 후 조치하겠습니다.</p>
            ) : (
              <>
                {reportRules.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    {reportRules.map((rule) => (
                      <label key={rule.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", cursor: "pointer", fontSize: "0.9em" }}>
                        <input type="checkbox" checked={selectedRuleIds.includes(rule.id)} onChange={(e) => {
                          setSelectedRuleIds((prev) => e.target.checked ? [...prev, rule.id] : prev.filter((id) => id !== rule.id));
                        }} />
                        {rule.title}
                      </label>
                    ))}
                  </div>
                )}
                <textarea
                  value={reportReason}
                  onChange={(e) => setReportReason(e.target.value)}
                  placeholder="신고 사유를 입력해주세요 (최소 10자)"
                  style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
                />
                {reportError && <p style={{ color: "var(--error)", fontSize: 14, marginBottom: 8 }}>{reportError}</p>}
                <button onClick={async () => {
                  if (reportReason.trim().length < 10) { setReportError("최소 10자 이상 입력해주세요."); return; }
                  setReportError("");
                  try { await api.report("episode", episode.id, reportReason.trim(), selectedRuleIds); setReportDone(true); }
                  catch (e: any) { setReportError(e.message || "신고 처리 중 오류가 발생했습니다."); }
                }} className="btn" style={{ width: "100%" }}>신고 제출</button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
