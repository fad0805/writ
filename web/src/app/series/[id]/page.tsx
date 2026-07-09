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

const STATUS_LABELS: Record<string, string> = { ongoing: "연재중", hiatus: "휴재", discontinued: "연재중단", completed: "완결" };
const STATUS_ICONS: Record<string, string> = { ongoing: "edit", hiatus: "moon", discontinued: "x", completed: "check" };

export default function NovelDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const [novel, setNovel] = useState<NovelData | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeData[]>([]);
  const [author, setAuthor] = useState<User | null>(null);
  const [isMine, setIsMine] = useState(false);
  const [isFollowing, setIsFollowing] = useState(false);
  const [isSeriesMuted, setIsSeriesMuted] = useState(false);
  const [isSeriesPinned, setIsSeriesPinned] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pinnedNotices, setPinnedNotices] = useState<NoticeData[]>([]);
  const [showSharePost, setShowSharePost] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [reportReason, setReportReason] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(false);

  useEffect(() => {
    const id = Number(Array.isArray(params.id) ? params.id[0] : params.id);
    if (isNaN(id)) return;
    api.getNovel(id)
      .then((d) => { setNovel(d.novel); setEpisodes(d.episodes); setAuthor(d.author); setIsMine(d.is_mine); setIsFollowing(d.is_following); setLoading(false); })
      .catch(() => setLoading(false));
    if (user) {
      fetch("/api/mutes/series", { credentials: "include" })
        .then((r) => r.json())
        .then((d) => setIsSeriesMuted((d.mutes || []).some((m: any) => m.novel_id === id)))
        .catch(() => {});
      setIsSeriesPinned((user as any).pinned_series?.includes(id) || false);
    }
    fetch(`/api/series/${id}/notices`, { credentials: "include" })
      .then((r) => r.json())
      .then((list) => setPinnedNotices((list as NoticeData[]).filter((n) => n.is_pinned)))
      .catch(() => {});
  }, [params.id, user]);

  const toggleFollow = async () => {
    if (!novel || !user) return;
    try {
      if (isFollowing) {
        await fetch(`/api/series/${novel.id}/unfollow`, { method: "POST", credentials: "include" });
        setIsFollowing(false);
      } else {
        await fetch(`/api/series/${novel.id}/follow`, { method: "POST", credentials: "include" });
        setIsFollowing(true);
      }
    } catch {}
  };

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
                {user && !isMine && (
                  <button className="action-btn" onClick={async () => {
                    if (isSeriesMuted) { await fetch(`/api/mutes/series/${novel.id}`, { method: "DELETE", credentials: "include" }); setIsSeriesMuted(false); }
                    else { await fetch(`/api/mutes/series/${novel.id}`, { method: "POST", credentials: "include" }); setIsSeriesMuted(true); }
                  }} title={isSeriesMuted ? "뮤트 해제" : "시리즈 뮤트"}>
                    <Icon name={isSeriesMuted ? "mute" : "bell"} />
                  </button>
                )}
                {novel.visibility !== "private" && <ShareButton url={`/series/${novel.id}`} />}
                {user && <button className="action-btn" onClick={() => setShowSharePost(true)} title="포스트로 공유"><Icon name="edit" /></button>}
                {user && !isMine && (
                  <button className="action-btn" onClick={() => { setShowReport(true); setReportReason(""); setReportError(""); setReportDone(false); }} title="신고">
                    <Icon name="flag" />
                  </button>
                )}
                {user && !isMine && (
                  <button onClick={toggleFollow} className={`btn btn-small ${isFollowing ? "btn-outline" : "btn-primary"}`}>
                    {isFollowing ? "팔로잉" : "팔로우"}
                  </button>
                )}
                {isMine && (
                  <>
                    <button className="action-btn" onClick={async () => {
                      const wasPinned = isSeriesPinned;
                      setIsSeriesPinned(!wasPinned);
                      const res = await fetch(`/api/${wasPinned ? "unpin" : "pin"}/series/${novel.id}`, { method: "POST", credentials: "include" });
                      if (!res.ok) { setIsSeriesPinned(wasPinned); const d = await res.json().catch(() => ({})); if (d.detail) alert(d.detail); }
                    }} title={isSeriesPinned ? "고정 해제" : "고정"} style={{ color: isSeriesPinned ? "var(--danger)" : undefined }}><Icon name={isSeriesPinned ? "pin_filled" : "pin"} /></button>
                    <button className="btn btn-small" onClick={() => router.push(`/series/${novel.id}/edit`)}>시리즈 편집</button>
                    <button className="btn btn-primary btn-small" onClick={() => router.push(`/series/${novel.id}/episodes/new`)}>새 에피소드</button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="novel-status">
          <span><Icon name={STATUS_ICONS[novel.status] || "edit"} /> {STATUS_LABELS[novel.status] || "연재중"}</span>
          <span><Icon name="book" /> 총 {novel.episode_count}화</span>
          {isMine && typeof novel.total_views === 'number' && <span><Icon name="eye" /> 총 {novel.total_views}회 조회</span>}
          {isMine && typeof (novel as any).followers_count === 'number' && <span><Icon name="user" /> {(novel as any).followers_count}명 팔로우</span>}
          <span><Icon name="lock" /> {novel.visibility === "public" ? "전체공개" : novel.visibility === "unlisted" ? "공개" : "비공개"}</span>
        </div>
        {novel.description && <p className="novel-description">{novel.description}</p>}
        {novel.tags && <p className="novel-tags"><Icon name="tag" /> {novel.tags.split(/[ ,]+/).filter(Boolean).map((t, i) => <span key={i} className="tag-spacing">{t}</span>)}</p>}
      </div>

      {pinnedNotices.length > 0 && (
        <div className="pinned-notices">
          {pinnedNotices.map((n) => (
            <div key={n.id} className="pinned-notice-item" onClick={() => router.push(`/series/${novel.id}/notices/${n.id}`)}>
              <span className="pinned-notice-icon"><Icon name="pin_filled" /></span>
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
          <div key={e.id} className={`episode-item${!e.is_published && !isMine ? " episode-item-private" : ""}`} onClick={() => router.push(`/series/${novel.id}/episodes/${e.id}`)}>
            <div className="episode-number">제 {e.episode_number}화</div>
            <div className="episode-info">
              <span className="episode-title" style={{ color: !e.is_published && !isMine ? "var(--text-dim)" : undefined }}>{e.title}{!e.is_published && !isMine ? " (비공개)" : ""}</span>
              <div className="episode-meta">
                {isMine && <span><Icon name={e.is_published ? "check" : "lock"} /> {e.is_published ? "공개" : "비공개"}</span>}
                {isMine && e.views !== undefined && <span><Icon name="eye" /> {e.views}</span>}
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
      {showSharePost && <SharePostModal url={`/series/${novel.id}`} title={novel.title} authorName={author?.display_name || author?.username} description={novel.description} tags={novel.tags} onClose={() => setShowSharePost(false)} />}
      {showReport && (
        <div className="reply-modal-backdrop active" onClick={() => setShowReport(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <button className="reply-modal-close" onClick={() => setShowReport(false)}>×</button>
            <h3>시리즈 신고</h3>
            {reportDone ? (
              <p style={{ color: "var(--text-secondary)", margin: "16px 0" }}>신고가 접수되었습니다. 검토 후 조치하겠습니다.</p>
            ) : (
              <>
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
                  try { await api.report("novel", novel.id, reportReason.trim()); setReportDone(true); }
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
