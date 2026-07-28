"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useMemo } from "react";
import { api, NovelData, EpisodeData } from "@/lib/api";
import Icon from "@/components/Icon";
import ShareButton from "@/components/ShareButton";
import SharePostModal from "@/components/SharePostModal";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { installCodeCopyButtons } from "@/lib/codeCopy";
import { sanitizeEpisode, sanitizeBasic } from "@/lib/sanitize";
import AudioPlayer from "@/components/AudioPlayer";
import { splitIntoPages } from "@/lib/pages";


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
  const [currentPage, setCurrentPage] = useState(0);
  const [comicPage, setComicPage] = useState(0);

  function renderEpisodeContent(html: string): string {
    let content = html;
    if (/<\/?[a-zA-Z]+[\s\/>]/.test(content)) {
      content = content.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
    } else {
      content = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    const codeBlocks: string[] = [];
    content = content.replace(/```(\w*)\r?\n([\s\S]*?)```/g, (_m, _lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code>${code.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')}</code></pre>`);
      return `\x00CODEBLOCK_${idx}\x00`;
    });
    content = content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    content = content.replace(/\*(.+?)\*/g, '<em>$1</em>');
    content = content.replace(/`(.+?)`/g, '<code>$1</code>');
    content = content.replace(/\n/g, '<br>');
    codeBlocks.forEach((block, i) => {
      content = content.replace(`\x00CODEBLOCK_${i}\x00`, block);
    });
    return content;
  }

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

  const pages = useMemo(() => {
    if (!episode?.content) return [""];
    if (!episode.page_mode) return [episode.content];
    return splitIntoPages(episode.content);
  }, [episode?.content, episode?.page_mode]);

  useEffect(() => {
    setCurrentPage(0);
    setComicPage(0);
  }, [episode?.id]);

  const totalPages = pages.length;
  const isRtl = episode?.reading_direction === "rtl";
  useEffect(() => {
    if (totalPages <= 1 && episode?.view_mode !== "comic") return;
    const onKey = (e: KeyboardEvent) => {
      if (episode?.view_mode === "comic") {
        const cm = episode.comic_view_mode || "paged";
        if (cm !== "paged") return;
        const imgs = episode.image_urls || [];
        if (imgs.length <= 1) return;
        if (e.key === "ArrowLeft") setComicPage((p) => isRtl ? Math.min(imgs.length - 1, p + 1) : Math.max(0, p - 1));
        else if (e.key === "ArrowRight") setComicPage((p) => isRtl ? Math.max(0, p - 1) : Math.min(imgs.length - 1, p + 1));
      } else {
        if (e.key === "ArrowLeft") setCurrentPage((p) => Math.max(0, p - 1));
        else if (e.key === "ArrowRight") setCurrentPage((p) => Math.min(totalPages - 1, p + 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [totalPages, episode?.view_mode, episode?.comic_view_mode, episode?.reading_direction, episode?.id, isRtl]);

  const touchStartX = useRef(0);
  useEffect(() => {
    if (episode?.view_mode === "comic") {
      const cm = episode.comic_view_mode || "paged";
      if (cm !== "paged") return;
      const images = episode.image_urls || [];
      if (images.length <= 1) return;
      const el = document.querySelector(".episode-comic-viewer-paged");
      if (!el) return;
      const onStart = (e: Event) => { touchStartX.current = (e as any).touches[0].clientX; };
      const onEnd = (e: Event) => {
        const dx = (e as any).changedTouches[0].clientX - touchStartX.current;
        if (Math.abs(dx) > 50) {
          if (isRtl) {
            if (dx > 0) setComicPage((p) => Math.min(images.length - 1, p + 1));
            else setComicPage((p) => Math.max(0, p - 1));
          } else {
            if (dx > 0) setComicPage((p) => Math.max(0, p - 1));
            else setComicPage((p) => Math.min(images.length - 1, p + 1));
          }
        }
      };
      el.addEventListener("touchstart", onStart, { passive: true });
      el.addEventListener("touchend", onEnd, { passive: true });
      return () => {
        el.removeEventListener("touchstart", onStart);
        el.removeEventListener("touchend", onEnd);
      };
    }
    if (totalPages <= 1) return;
    const el = document.querySelector(".episode-view-paged-wrap");
    if (!el) return;
    const onStart = (e: Event) => { touchStartX.current = (e as any).touches[0].clientX; };
    const onEnd = (e: Event) => {
      const dx = (e as any).changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 50) {
        if (dx > 0) setCurrentPage((p) => Math.max(0, p - 1));
        else setCurrentPage((p) => Math.min(totalPages - 1, p + 1));
      }
    };
    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchend", onEnd, { passive: true });
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchend", onEnd);
    };
  }, [totalPages, episode?.view_mode, episode?.comic_view_mode, episode?.reading_direction, episode?.id, isRtl]);

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
        <div className="episode-header-btns" style={{ marginBottom: 12 }}>
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
        <h2>제 {episode.episode_number}화: {episode.title}</h2>
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
            {episode.audio_url && <div className="episode-audio"><AudioPlayer src={episode.audio_url} /></div>}
            {episode.view_mode === "comic" ? (
              (() => {
                const images = episode.image_urls || [];
                const comicViewMode = episode.comic_view_mode || "paged";
                if (images.length === 0) return <div className="empty-state">이미지가 없습니다</div>;
                return (
                  <>
                    {comicViewMode === "paged" ? (
                      <div className="episode-comic-viewer-paged" onClick={(e) => {
                        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                        const x = e.clientX - rect.left;
                        if (isRtl) {
                          if (x < rect.width / 3 && comicPage < images.length - 1) setComicPage(comicPage + 1);
                          else if (x > (rect.width / 3) * 2 && comicPage > 0) setComicPage(comicPage - 1);
                        } else {
                          if (x < rect.width / 3 && comicPage > 0) setComicPage(comicPage - 1);
                          else if (x > (rect.width / 3) * 2 && comicPage < images.length - 1) setComicPage(comicPage + 1);
                        }
                      }}>
                        <img src={images[comicPage]} alt={`만화 ${comicPage + 1}페이지`} />
                        <button type="button" className="episode-comic-paged-arrow left" disabled={isRtl ? comicPage === images.length - 1 : comicPage === 0} onClick={(e) => { e.stopPropagation(); setComicPage(isRtl ? Math.min(images.length - 1, comicPage + 1) : Math.max(0, comicPage - 1)); }}>‹</button>
                        <button type="button" className="episode-comic-paged-arrow right" disabled={isRtl ? comicPage === 0 : comicPage === images.length - 1} onClick={(e) => { e.stopPropagation(); setComicPage(isRtl ? Math.max(0, comicPage - 1) : Math.min(images.length - 1, comicPage + 1)); }}>›</button>
                      </div>
                    ) : (
                      <div className="episode-comic-viewer-scroll">
                        {images.map((url, i) => (
                          <img key={i} src={url} alt={`만화 ${i + 1}페이지`} />
                        ))}
                      </div>
                    )}
                    {comicViewMode === "paged" && (
                      <div className="episode-view-page-nav">
                        <button type="button" className="episode-view-page-arrow" disabled={isRtl ? comicPage === images.length - 1 : comicPage === 0} onClick={() => setComicPage(isRtl ? Math.min(images.length - 1, comicPage + 1) : Math.max(0, comicPage - 1))}>‹</button>
                        <div className="episode-view-page-slider-wrap">
                          <input type="range" min={0} max={images.length - 1} value={comicPage} onChange={(e) => setComicPage(Number(e.target.value))} className="episode-view-page-slider" />
                        </div>
                        <button type="button" className="episode-view-page-arrow" disabled={isRtl ? comicPage === 0 : comicPage === images.length - 1} onClick={() => setComicPage(isRtl ? Math.max(0, comicPage - 1) : Math.min(images.length - 1, comicPage + 1))}>›</button>
                        <span className="episode-view-page-info">{comicPage + 1} / {images.length}</span>
                      </div>
                    )}
                  </>
                );
              })()
            ) : (
              <>
                <div className="episode-view-paged-wrap">
                  <div ref={bodyRef} className="episode-body" dangerouslySetInnerHTML={{ __html: sanitizeEpisode(renderEpisodeContent(pages[currentPage] || "")) }} />
                  {pages.length > 1 && (
                    <>
                      <button type="button" className="episode-view-page-side-arrow left" disabled={currentPage === 0} onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}>‹</button>
                      <button type="button" className="episode-view-page-side-arrow right" disabled={currentPage === pages.length - 1} onClick={() => setCurrentPage((p) => Math.min(pages.length - 1, p + 1))}>›</button>
                    </>
                  )}
                </div>
                {pages.length > 1 && (
                  <div className="episode-view-page-nav">
                    <button type="button" className="episode-view-page-arrow" disabled={currentPage === 0} onClick={() => setCurrentPage(currentPage - 1)}>‹</button>
                    <div className="episode-view-page-slider-wrap">
                      <input type="range" min={0} max={pages.length - 1} value={currentPage} onChange={(e) => setCurrentPage(Number(e.target.value))} className="episode-view-page-slider" />
                    </div>
                    <button type="button" className="episode-view-page-arrow" disabled={currentPage === pages.length - 1} onClick={() => setCurrentPage(currentPage + 1)}>›</button>
                    <span className="episode-view-page-info">{currentPage + 1} / {pages.length}</span>
                  </div>
                )}
              </>
            )}
            {episode.comment && <div className="episode-comment" dangerouslySetInnerHTML={{ __html: sanitizeBasic(episode.comment) }} />}
          </>
        )}
        <div className="episode-footer">
        <div className="episode-nav">
          <div className="episode-nav-side">
            {prevEp ? (
              <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${prevEp.id}`)}>
                <span className="episode-nav-arrow">←</span> <span className="episode-nav-text">제 {prevEp.episode_number} 화 ({prevEp.title})</span>
              </button>
            ) : (
              <span className="episode-nav-none">이전 화가 없습니다</span>
            )}
          </div>
          <Link href={`/series/${novel.id}`} className="btn btn-outline">목차</Link>
          <div className="episode-nav-side">
            {nextEp ? (
              <button className="btn btn-outline" onClick={() => router.push(`/series/${novel.id}/episodes/${nextEp.id}`)}>
                <span className="episode-nav-text">제 {nextEp.episode_number} 화 ({nextEp.title})</span> <span className="episode-nav-arrow">→</span>
              </button>
            ) : (
              <span className="episode-nav-none">다음 화가 없습니다</span>
            )}
          </div>
        </div>
        </div>
      </article>
      {showSharePost && <SharePostModal
        url={`/series/${novel.id}/episodes/${episode.id}`}
        title={novel.title}
        authorName={novel.author?.display_name || novel.author?.username}
        description={episode?.summary}
        tags={novel.tags}
        content={`「${episode.episode_number}화: ${episode.title}」`}
        onClose={() => setShowSharePost(false)}
      />}
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
