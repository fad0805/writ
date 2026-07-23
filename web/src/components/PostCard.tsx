"use client";
import { PostData, NovelData, User, EpisodeData, api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import EditModal from "./EditModal";
import ReplyModal from "./ReplyModal";
import ClickableCover from "./ClickableCover";
import PostForm from "./PostForm";
import Icon from "./Icon";
import Avatar from "./Avatar";
import MiniPostCard from "./MiniPostCard";
import EmojiPicker from "./EmojiPicker";
import { useAuth } from "@/lib/auth";
import ShareButton from "@/components/ShareButton";
import { hashColor } from "@/lib/avatar";
import { renderCustomEmojis, injectEmojis, CustomEmoji, subscribeEmojis } from "@/lib/emojis";
import { sanitizePost, sanitizeName } from "@/lib/sanitize";
import { installCodeCopyButtons } from "@/lib/codeCopy";

const VIS_ICONS: Record<string, string> = {
  public: "globe", home: "home", followers: "lock", mention: "mail",
};

function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  if (abs < 60000) return `${Math.floor(abs / 1000)}초`;
  if (abs < 3600000) return `${Math.floor(abs / 60000)}분 ${Math.floor((abs % 60000) / 1000)}초`;
  if (abs < 86400000) return `${Math.floor(abs / 3600000)}시간`;
  return `${Math.floor(abs / 86400000)}일`;
}

export function rewriteLinks(text: string, validMentions?: Set<string>): string {
  text = text.replace(
    /(?<!<[^>]*)(^|>|\s)#([\p{L}\p{N}_]+)/gu, 
    (_m, before, tag) => {
      return `${before}<a href="/explore?q=%23${encodeURIComponent(tag)}" class="hashtag-link">#${tag}</a>`;
    }
  );

  text = text.replace(
    /(?<!<[^>]*)(?<!href=")(?<!src=")(^|>| |\s)(https?:\/\/[^\s<>"')\]]+)/g,
    (_m: string, before: string, url: string) => {
      const isLocal = typeof window !== "undefined" && url.startsWith(window.location.origin);
      const targetUrl = isLocal ? url.replace(window.location.origin, "") : url;
      let display = url.replace(/^https?:\/\//, "");
      if (display.length > 40) display = display.slice(0, 37) + "...";
      return `${before}<a href="${targetUrl}"${isLocal ? "" : ' target="_blank" rel="noopener noreferrer"'}>${display}</a>`;
    }
  );
  return text;
}

export default function PostCard({ post, onUpdate, onDelete, onReply, onRewrite, current, hideContext, selected, readonly }: { post: PostData; onUpdate?: (updated?: PostData) => void; onDelete?: () => void; onReply?: (newPost?: PostData) => void; onRewrite?: (content: string, visibility: string, replyTo?: { id: number; number: string; content: string; author: any; visibility: string } | null) => void; current?: boolean; hideContext?: boolean; selected?: boolean; readonly?: boolean }) {
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const [showReply, setShowReply] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [showRewrite, setShowRewrite] = useState(false);
  const [showPollResults, setShowPollResults] = useState(false);
  const [pollRefreshing, setPollRefreshing] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [reportReason, setReportReason] = useState("");
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(false);
  const [reportForward, setReportForward] = useState(false);
  const [reportRules, setReportRules] = useState<{ id: number; title: string; description: string }[]>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<number[]>([]);
  const [liked, setLiked] = useState(post.liked);
  const [boosted, setBoosted] = useState(post.boosted);
  const [bookmarked, setBookmarked] = useState(post.bookmarked);
  const [pinned, setPinned] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [likesCount, setLikesCount] = useState(post.likes_count);
  const [boostsCount, setBoostsCount] = useState(post.boosts_count);
  const [seriesMatch, setSeriesMatch] = useState<RegExpMatchArray | null>(null);
  const [episodeMatch, setEpisodeMatch] = useState<RegExpMatchArray | null>(null);

  const [emojiList, setEmojiList] = useState<CustomEmoji[]>(() => {
    if (typeof window !== "undefined" && (window as any).__emojiCache)
      return (window as any).__emojiCache as CustomEmoji[];
    return [];
  });
  useEffect(() => {
    const unsubscribe = subscribeEmojis((list) => {
      setEmojiList((prev) => {
        if (prev === list) return prev;
        if (prev.length === list.length && prev.every((e, i) => e.keyword === list[i]?.keyword && e.url === list[i]?.url)) return prev;
        return [...list];
      });
    });
    return () => unsubscribe();
  }, []);
  const [reactions, setReactions] = useState(post.reactions || {});
  const [myReaction, setMyReaction] = useState(post.my_reaction || null);
  const reactionEmojiMap = useMemo(() => {
    const m = (window as any).__emojiMap as Record<string, string> | undefined;
    if (m && Object.keys(m).length > 0) return m;
    const map: Record<string, string> = {};
    for (const e of emojiList) if (e.keyword && e.url) map[e.keyword] = e.url;
    if (Object.keys(map).length > 0) {
      (window as any).__emojiMap = map;
    }
    return map;
  }, [emojiList]);
const localReactionEmojiMap = useMemo(() => {
  const m = (window as any).__localEmojiMap as Record<string, string> | undefined;
  if (m && Object.keys(m).length > 0) return m;
  const map: Record<string, string> = {};
  for (const e of emojiList) {
    if (e.keyword && e.url && e.url.includes('/emojis/local/')) {
      map[e.keyword] = e.url;
    }
  }
  if (Object.keys(map).length > 0) {
    (window as any).__localEmojiMap = map;
  }
  return map;
}, [emojiList]);

  useEffect(() => {
    if (currentUser?.pinned_posts) setPinned(currentUser.pinned_posts.includes(post.id));
  }, [currentUser, post.id]);

  useEffect(() => {
    setLiked(post.liked);
    setBoosted(post.boosted);
    setBookmarked(post.bookmarked);
    setLikesCount(post.likes_count);
    setBoostsCount(post.boosts_count);
    setReactions(post.reactions || {});
    setMyReaction(post.my_reaction || null);
  }, [post.liked, post.boosted, post.bookmarked, post.likes_count, post.boosts_count, post.content, post.summary, post.reactions, post.my_reaction]);

  useEffect(() => {
    if (!post.poll_data) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [post.poll_data]);

  const toggleLike = () => {
    const next = !liked;
    setLiked(next);
    setLikesCount(Math.max(0, likesCount + (next ? 1 : -1)));
    (next ? api.like(post.id) : api.unlike(post.id)).catch(() => {
      setLiked(!next);
      setLikesCount(Math.max(0, likesCount + (next ? -1 : 1)));
    });
  };

  const toggleBookmark = () => {
    const next = !bookmarked;
    setBookmarked(next);
    (next ? api.bookmark(post.id) : api.unbookmark(post.id)).catch(() => {
      setBookmarked(!next);
    });
  };

  const toggleBoost = async () => {
    const prevCount = boostsCount;
    try {
      if (boosted) {
        setBoosted(false);
        setBoostsCount(Math.max(0, boostsCount - 1));
        await api.unboost(post.id);
      }
      else {
        setBoosted(true);
        setBoostsCount(boostsCount + 1);
        await api.boost(post.id);
      }
    } catch {
      setBoosted(false);
      setBoostsCount(prevCount);
    }
  };

  const handleDelete = async () => {
    const isAdminDeletingOther = currentUser?.is_admin && !post.is_mine;
    if (!confirm(isAdminDeletingOther ? "관리자 권한으로 이 게시글을 삭제하시겠습니까?" : "삭제하시겠습니까?")) return;
    if (onDelete) onDelete();
    else if (onUpdate) onUpdate();
    else if (current) router.back();
    try { await api.deletePost(post.id); } catch {}
  };

  const handleReport = async () => {
    if (selectedRuleIds.length === 0 && reportReason.trim().length < 10) { setReportError("규칙을 선택하거나 사유를 10자 이상 입력해주세요."); return; }
    setReportError("");
    try {
      const form = new FormData();
      form.append("target_type", "post");
      form.append("target_id", String(post.id));
      form.append("reason", reportReason.trim());
      form.append("forward_to_remote", reportForward ? "true" : "");
      form.append("rule_ids", JSON.stringify(selectedRuleIds));
      const res = await fetch("/api/reports", { method: "POST", credentials: "include", body: form });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "신고 실패"); }
      setReportDone(true);
      setShowReport(false);
    } catch (e: any) {
      setReportError(e.message || "신고 처리 중 오류가 발생했습니다.");
    }
  };

  useEffect(() => {
    if (post._emojis) injectEmojis(post._emojis);
  }, [post._emojis]);

  const [nowTime, setNowTime] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNowTime(Date.now()), 10000); return () => clearInterval(id); }, []);
  const timeStr = post.created_at ? (() => {
    const t = new Date(post.created_at).getTime();
    const diff = nowTime - t;
    if (diff < 86400000) {
      if (diff < 60000) return `${Math.floor(diff / 1000)}초 전`;
      if (diff < 3600000) return `${Math.floor(diff / 60000)}분 전`;
      return `${Math.floor(diff / 3600000)}시간 전`;
    }
    return new Date(post.created_at).toLocaleString("ko-KR", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).replace(/\. /g, "-").replace(/\.$/, "");
  })() : "";

  const validMentions = useMemo(() => new Set(post.mentioned_handles || []), [post.mentioned_handles]);

  // 2. 순수한 HTML 변환 함수 (Setter 함수들 완전 제거)
  const buildContentHtml = () => {
    let html = post.content || "";

    // 🌟 [핵심 개선] 컴포넌트 state뿐만 아니라 window 전역 캐시 및 로컬 맵을 무조건 총동원합니다.
    const globalCache = (typeof window !== "undefined" && (window as any).__emojiCache) || [];
    const activeEmojis = [...emojiList, ...globalCache];

    // 중복 제거 (keyword 기준)
    const uniqueEmojis = Array.from(
      new Map(activeEmojis.map(e => [e.keyword, e])).values()
    );

    // Strip "RE: https://..." from quote posts
    if ((post as any).quote_of_id || (post as any).quote_of_ap_id) {
      html = html.replace(/(?:<span[^>]*>)?[\s\n]*RE:[\s\n]*(?:<a[^>]*>.*?<\/a>|https?:\/\/[^\s<>]+)[\s\n]*(?:<\/span>)?(?:[\s\n]*<br\s*\/?>)*/gi, '');
    }

    // 본문에서 series, episode 라인을 앞뒤 공백/줄바꿈 포함하여 완전히 삭제
    html = html.replace(/(?:<br\s*\/?>|\n|^)\s*(?:series|episode):\s*(?:<a[^>]*>.*?<\/a>|https?:\/\/[^\s<>]+)\s*(?:<br\s*\/?>|\n|$)/gi, '\n');

    if (/<\/?[a-zA-Z]+[\s\/>]/.test(html) || /&[a-z]+;/.test(html)) {
      html = html.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
    } else {
      html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    const codeBlocks: string[] = [];
    html = html.replace(/```(\w*)\r?\n([\s\S]*?)```/g, (_m, _lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code>${code.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+$/, '')}</code></pre>`);
      return `\x00CODEBLOCK_${idx}\x00`;
    });
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`(.+?)`/g, '<code>$1</code>');
    html = html.replace(/\n/g, '<br>');
    codeBlocks.forEach((block, i) => {
      html = html.replace(`\x00CODEBLOCK_${i}\x00`, block);
    });
    html = renderCustomEmojis(html, uniqueEmojis);
    html = rewriteLinks(html, validMentions);
    return html;
  };


  // series/episode 매칭 추출용 Effect
  useEffect(() => {
    const rawContent = post.content || "";
    const seriesMatches = rawContent.match(/(?:<br\s*\/?>|\n|^)\s*(series):\s*(?:<a[^>]*href="([^"]+)"[^>]*>.*?<\/a>|(https?:\/\/[^\s<>]+))/i);
    const episodeMatches = rawContent.match(/(?:<br\s*\/?>|\n|^)\s*(episode):\s*(?:<a[^>]*href="([^"]+)"[^>]*>.*?<\/a>|(https?:\/\/[^\s<>]+))/i);
    setSeriesMatch(seriesMatches && (seriesMatches[2] || seriesMatches[3]) ? seriesMatches : null);
    setEpisodeMatch(episodeMatches && (episodeMatches[2] || episodeMatches[3]) ? episodeMatches : null);
  }, [post.id, post.content, post.summary]);

  // contentHtml: emojiList 변경 시 즉시 재계산하여 이모지 렌더링 깜빡임 방지
  const contentHtml = useMemo(() => sanitizePost(buildContentHtml()), [post.id, post.content, post.summary, emojiList]);

  // 4. 코드 복사 버튼 플러그인 Effect (기존 코드 그대로 유지)
  useEffect(() => {
    if (cardRef.current) installCodeCopyButtons(cardRef.current);
  }, [contentHtml, post.content]);

  // Extract quoted post URL from content
  type QuotedSeries = { type: "series"; novel: NovelData; author: User };
  type QuotedEpisode = { type: "episode"; episode: EpisodeData; novel: NovelData; author: User };
  const [quotedPost, setQuotedPost] = useState<PostData | null>(null);
  const [quotedSeries, setQuotedSeries] = useState<QuotedSeries | null>(null);
  const [quotedEpisode, setQuotedEpisode] = useState<QuotedEpisode | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [viewerIndex, setViewerIndex] = useState(-1);
  const [viewerZoom, setViewerZoom] = useState(1);
  const [viewerPan, setViewerPan] = useState({ x: 0, y: 0 });
  const viewerImgRef = useRef<HTMLImageElement>(null);
  const lastTouchDist = useRef(0);
  const lastTouchCenter = useRef({ x: 0, y: 0 });
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0 });
  const panOrigin = useRef({ x: 0, y: 0 });
  const swipeStartX = useRef(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const [revealedSensitive, setRevealedSensitive] = useState(false);
  useEffect(() => {
    if (viewerIndex < 0) return;
    setViewerZoom(1);
    setViewerPan({ x: 0, y: 0 });
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewerIndex(-1);
      else if (e.key === "ArrowLeft" && viewerIndex > 0) setViewerIndex(viewerIndex - 1);
      else if (e.key === "ArrowRight" && viewerIndex < (post as any).media_attachments.length - 1) setViewerIndex(viewerIndex + 1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [viewerIndex]);
  const handleViewerWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    setViewerZoom((z) => Math.min(5, Math.max(0.5, z + delta)));
  }, []);
  const handleViewerTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastTouchDist.current = Math.hypot(dx, dy);
      lastTouchCenter.current = {
        x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
        y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
      };
    } else if (e.touches.length === 1 && viewerZoom > 1) {
      isPanning.current = true;
      panStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      panOrigin.current = { ...viewerPan };
    } else if (e.touches.length === 1) {
      swipeStartX.current = e.touches[0].clientX;
    }
  }, [viewerZoom, viewerPan]);
  const handleViewerTouchMove = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      if (lastTouchDist.current > 0) {
        const scale = dist / lastTouchDist.current;
        setViewerZoom((z) => Math.min(5, Math.max(0.5, z * scale)));
      }
      lastTouchDist.current = dist;
    } else if (e.touches.length === 1 && isPanning.current) {
      e.preventDefault();
      const dx = e.touches[0].clientX - panStart.current.x;
      const dy = e.touches[0].clientY - panStart.current.y;
      setViewerPan({ x: panOrigin.current.x + dx, y: panOrigin.current.y + dy });
    }
  }, []);
  const handleViewerTouchEnd = useCallback((e: React.TouchEvent) => {
    if (swipeStartX.current !== 0 && viewerZoom <= 1) {
      const dx = e.changedTouches[0].clientX - swipeStartX.current;
      if (Math.abs(dx) > 60) {
        const media = (post as any).media_attachments || [];
        if (dx > 0 && viewerIndex > 0) setViewerIndex(viewerIndex - 1);
        else if (dx < 0 && viewerIndex < media.length - 1) setViewerIndex(viewerIndex + 1);
      }
    }
    swipeStartX.current = 0;
    lastTouchDist.current = 0;
    isPanning.current = false;
  }, [viewerZoom, viewerIndex, post]);
  const handleViewerDblClick = useCallback(() => {
    setViewerZoom((z) => {
      if (z > 1) { setViewerPan({ x: 0, y: 0 }); return 1; }
      return 2;
    });
  }, []);
  const handleViewerMouseDown = useCallback((e: React.MouseEvent) => {
    if (viewerZoom > 1) {
      isPanning.current = true;
      panStart.current = { x: e.clientX, y: e.clientY };
      panOrigin.current = { ...viewerPan };
      e.preventDefault();
    }
  }, [viewerZoom, viewerPan]);
  const handleViewerMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning.current) {
      const dx = e.clientX - panStart.current.x;
      const dy = e.clientY - panStart.current.y;
      setViewerPan({ x: panOrigin.current.x + dx, y: panOrigin.current.y + dy });
    }
  }, []);

  const handleViewerMouseUp = useCallback(() => { isPanning.current = false; }, []);

  useEffect(() => {
    if (!showMoreActions) return;
    const handler = () => setShowMoreActions(false);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [showMoreActions]);

  // Handle stored quote reference from ActivityPub (quote_of_id / quote_of_ap_id)
  useEffect(() => {
    if (quotedPost || quotedSeries || quotedEpisode || loadingQuote) return;
    const qid = (post as any).quote_of_id;
    const qApId = (post as any).quote_of_ap_id;
    if (qid) {
      setLoadingQuote(true);
      fetch(`/api/posts/${qid}?reply_limit=0&reply_offset=0`, { credentials: "include" })
        .then(r => { if (r.ok) return r.json(); throw new Error(); })
        .then(d => { setQuotedPost(d); setLoadingQuote(false); })
        .catch(() => setLoadingQuote(false));
    } else if (qApId) {
      setLoadingQuote(true);
      const form = new FormData(); form.append("url", qApId);
      fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form })
        .then(r => { if (r.ok) return r.json(); throw new Error(); })
        .then(d => { if (d._emojis) { injectEmojis(d._emojis); } setQuotedPost(d); setLoadingQuote(false); })
        .catch(() => setLoadingQuote(false));
    }
  }, [post.id, (post as any).quote_of_id, (post as any).quote_of_ap_id]);

// Detect series/episode share URLs in content (e.g. "series: https://.../series/123")
  useEffect(() => {
    // 🌟 [추가] 중요: 포스트가 새로 바뀌었을 때(또는 주소가 없을 때) 이전 포스트의 카드 데이터를 초기화합니다.
    const match = seriesMatch || episodeMatch;
    if (!match) {
      setQuotedSeries(null);
      setQuotedEpisode(null);
      return;
    }

    if (loadingQuote) return;

    const url = typeof match === 'string' ? match : (match[2] || match[3] || match[0]); 
    if (!url) return;
    // 🌟 [정규식 수정] 실제 주소 스펙에 맞춤
    // 1. 에피소드 주소 (ex: /series/1/episodes/5)
    const epMatch = url.match(/\/series\/(\d+)\/episodes\/(\d+)/);
    // 2. 시리즈 단독 주소 (ex: /series/1)
    const seriesOnlyMatch = url.match(/\/series\/(?:by-number\/[^/]+\/)?([a-zA-Z0-9]+)(?:\?.*)?$/);
    if (epMatch) {
      const novelId = parseInt(epMatch[1]);
      const episodeId = parseInt(epMatch[2]);
      setLoadingQuote(true);
      const form = new FormData();
      form.append("url", url);

      fetch("/api/fetch-episode", {
        method: "POST",
        credentials: "include",
        body: form
      })
        .then((r) => { if (!r.ok) throw new Error("Episode not found"); return r.json(); })
        .then((d) => { if (d && d.type === "episode" && d.episode) setQuotedEpisode(d); })
        .then(() => setLoadingQuote(false))
        .catch(() => setLoadingQuote(false));
    } else if (seriesOnlyMatch) {
      setLoadingQuote(true); // 🌟 누락되었던 로딩 시작 세팅 추가
      const form = new FormData();
      form.append("url", url);

      fetch("/api/fetch-series", {
        method: "POST",
        credentials: "include",
        body: form
      })
      .then((r) => {
        if (!r.ok) throw new Error("Series not found");
        return r.json();
      })
      .then((d) => {
        if (!d) return;
        if (d.type === "series" && d.novel) {
          setQuotedSeries(d);
        }
      })
      .then(() => setLoadingQuote(false))
      .catch((err) => {
        console.error("시리즈 연동 실패:", err);
        setLoadingQuote(false);
      });
    }
  // 🌟 의존성 배열에 seriesMatch와 episodeMatch를 추가해 주어야 
  // 주소가 먼저 파싱되어 나왔을 때 이 이펙트가 기민하게 감지하고 fetch를 쏩니다.
  }, [post.id, seriesMatch, episodeMatch]);

  const handleContentClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href');
    if (href && href.startsWith('/')) {
      e.preventDefault();
      e.stopPropagation();
      router.push(href);
    }
  };

  const _renderMedia = () => {
    const postSensitive = (post as any).is_sensitive || (post.author as any)?.is_sensitive || !!(post as any).summary;
    const media = (post as any).media_attachments || [];
    if (!media.length) return null;
    const n = media.length;
    const gridColumns = n <= 2 ? n : n <= 4 ? 2 : 3;
    return (
      <div style={{ position: "relative", marginTop: 8, overflow: "hidden", borderRadius: 8 }}>
        <div className="post-media-grid" style={{ display: "grid", gridTemplateColumns: `repeat(${gridColumns}, 1fr)`, gap: 4 }}>
          {media.slice(0, 16).map((m: any, i: number) => {
            const blurred = postSensitive && !revealedSensitive;
            return m.type === "video" ? (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden" }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 8, zIndex: 1 }} />}
                <video src={m.url} controls style={{ width: "100%", maxHeight: 300, borderRadius: 8, objectFit: "contain", background: "#000", filter: blurred ? "blur(20px)" : "none" }} />
              </div>
            ) : (
              <div key={i} style={{ position: "relative", lineHeight: 0, overflow: "hidden" }}>
                {blurred && <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.6)", borderRadius: 8, zIndex: 1 }} />}
                <img src={m.url} alt={m.alt || ""} style={{ width: "100%", maxHeight: 300, borderRadius: 8, objectFit: "contain", background: "#000", cursor: blurred ? "default" : "pointer", filter: blurred ? "blur(20px)" : "none" }} onClick={(e) => { if (!blurred) { e.stopPropagation(); setViewerIndex(i); } }} />
              </div>
            );
          })}
        </div>
        {postSensitive && !revealedSensitive && (
          <div onClick={(e) => { e.stopPropagation(); e.preventDefault(); setRevealedSensitive(true); }} style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2, cursor: "pointer", color: "#fff", fontSize: 13, fontWeight: 600 }}>
            <span style={{ fontSize: 12, fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>클릭하여 표시</span>
          </div>
        )}
        {postSensitive && revealedSensitive && (
          <button onClick={(e) => { e.stopPropagation(); setRevealedSensitive(false); }} style={{ position: "absolute", top: 8, right: 8, zIndex: 2, background: "rgba(0,0,0,0.6)", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, padding: "3px 10px", cursor: "pointer" }}>가리기</button>
        )}
      </div>
    );
  };

  if (!post || !post.author) return null;

  return (
    <>
      <div ref={cardRef} className={`post-card${current ? " current" : ""}${selected ? " selected" : ""}${post.visibility === "mention" ? " mention-card" : ""}`} onClick={(e) => { if (current || (e.target as HTMLElement).closest('a')) return; router.push(post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`); }}>
        {post.boosted_by && (
          <div className={`boost-badge${currentUser?.id === post.boosted_by.id ? " boost-self" : ""}`}>
            <Icon name="refresh" size={12} /> <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.boosted_by.display_name || post.boosted_by.username, emojiList, 14)) }} />님이 부스트
          </div>
        )}
        <div className="post-header">
          <Link href={`/@${post.author.username}`} className="post-author-avatar-link no-underline" onClick={(e) => e.stopPropagation()}>
            <Avatar user={post.author} className="post-author-avatar flex items-center justify-center text-white font-bold text-sm" />
          </Link>
          <div className="post-name-wrap">
            <Link href={`/@${post.author.username}`} className="post-author" onClick={(e) => e.stopPropagation()}>
              <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.author.display_name, emojiList, 14)) }} /> {(post.author.role === "admin" || post.author.role === "moderator" || post.author.role === "owner") && (post.author as any).show_badge && <Icon name={post.author.role === "owner" ? "books_solid" : "shield_filled"} style={{ color: post.author.role === "owner" ? "var(--accent)" : post.author.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.65em", verticalAlign: "middle", marginLeft: 2 }} title={post.author.role === "owner" ? "오너" : post.author.role === "admin" ? "관리자" : "조율자"} />}
            </Link>
            <Link href={`/@${post.author.username}`} className="post-username" onClick={(e) => e.stopPropagation()}>
              @{post.author.display_handle || post.author.username}
            </Link>
            {post.author.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.65em", verticalAlign: "middle", color: "var(--text-muted)", marginLeft: 2 }} />}
          </div>
          <span className="post-time">
            <span className={`vis-badge vis-${post.visibility}`}>
              <Icon name={VIS_ICONS[post.visibility] || "globe"} />
            </span>
            {post.ap_id && post.ap_id.startsWith("http") && post.author?.username?.includes("@") ? (
              <a href={post.ap_id} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="no-underline" style={{ color: "inherit" }}>{timeStr}</a>
            ) : (
              timeStr
            )}
          </span>
        </div>
        {!hideContext && post.reply_context && (
          <Link href={post.reply_context.number ? `/@${post.reply_context.author.username}/${post.reply_context.number}` : `/post/${post.reply_context.id}`} className={`reply-context${post.reply_context.visibility === "mention" ? " mention-context" : ""}`} onClick={(e) => e.stopPropagation()}>
            <span className="reply-context-label">답글 대상</span>
            <strong dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.reply_context.author.display_name || post.reply_context.author.username, emojiList, 14)) }} />
            <span>@{post.reply_context.author.username}</span>
            <p dangerouslySetInnerHTML={{ __html: (() => {
              const hasCw = !!(post.reply_context as any).summary || !!(post.reply_context as any).is_sensitive;
              if (hasCw) {
                const cwLabel = (post.reply_context as any).summary || "내용 숨김";
                return `<span style="opacity:0.5;font-size:0.9em">🔒 ${cwLabel}</span>`;
              }
              const rawText = (post.reply_context.content || "");
              const text = rawText.slice(0, 90);
              let html = text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
              html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
              html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
              html = html.replace(/\n/g, '<br>');
              html = renderCustomEmojis(html, emojiList);
              html = rewriteLinks(html, validMentions);
              if (rawText.length > 90) html += "...";
              return sanitizePost(html);
            })() }} />
          </Link>
        )}
        {post.summary ? (
          <details className="cw-box">
            <summary onClick={(e) => e.stopPropagation()}>⚠️ {post.summary}</summary>
            <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
            {(post as any).media_attachments?.length > 0 && _renderMedia()}
            {post.link_preview && !(post as any).quote_of_id && !(post as any).quote_of_ap_id && (() => {
                const lp = post.link_preview!;
                const isLocalLink = (() => { try { return new URL(lp.url).hostname === window.location.hostname; } catch { return false; } })();
                const lpImage = isLocalLink ? ((window as any).__serverLogo || lp.image) : lp.image;
                return (
              <a href={lp.url} target="_blank" rel="noopener noreferrer" className="link-preview-card" onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 12, marginTop: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
                {lpImage && <img src={lpImage} alt="" style={{ width: 80, height: 80, borderRadius: isLocalLink ? 16 : 6, objectFit: "contain", flexShrink: 0, background: isLocalLink ? "var(--bg-tertiary)" : undefined }} onError={(e) => (e.target as HTMLElement).style.display = "none"} />}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lp.title}</div>
                  {lp.description && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{lp.description}</div>}
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{(() => { try { return new URL(lp.url).hostname; } catch { return ""; } })()}</div>
                </div>
              </a>
                );
              })()}
          </details>
        ) : (
          <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
        )}
        {!post.summary && (post as any).media_attachments?.length > 0 && _renderMedia()}
        {post.poll_data && (
          (() => {
            const total = post.poll_data!.options.reduce((s, o) => s + (o.votes_count || 0), 0);
            const isExpired = post.poll_data!.expires_at && new Date(post.poll_data!.expires_at).getTime() < now;
            const showResults = showPollResults || post.my_vote != null || isExpired || readonly || post.is_mine;
            return <div className="poll-box" style={{ marginTop: 8, padding: 10, borderRadius: 8, background: "var(--bg-tertiary)" }}>
              {post.poll_data!.options.map((opt, i) => {
                const pct = showResults && total > 0 ? Math.round(((opt.votes_count || 0) / total) * 100) : 0;
                const isSelected = post.my_vote === i;
                const canVote = !showResults && !isExpired && post.my_vote == null && !readonly && !post.is_mine;
                return (
                  <div
                    key={i}
                    className={`poll-option${isSelected ? " selected" : ""}${canVote ? " votable" : ""}`}
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!canVote) return;
                      try {
                        const result = await api.vote(post.id, i);
                        if (result.post) {
                          Object.assign(post, result.post);
                        }
                        if (onUpdate) onUpdate();
                        else window.dispatchEvent(new Event("postchange"));
                      } catch (err: any) { alert(err.message); }
                    }}
                    style={{
                      position: "relative", padding: "8px 10px", marginBottom: 4, borderRadius: 6,
                      border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                      background: isSelected ? "color-mix(in srgb, var(--accent) 15%, transparent)" : "var(--bg-secondary)",
                      cursor: canVote ? "pointer" : "default", overflow: "hidden",
                      transition: "all 0.15s",
                    }}
                  >
                    {showResults && <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${pct}%`, background: "color-mix(in srgb, var(--accent) 12%, transparent)", borderRadius: 6, transition: "width 0.3s" }} />}
                    <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontWeight: isSelected ? 600 : 400, fontSize: 14 }}>{opt.text}</span>
                      {showResults && <span style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 40, textAlign: "right" }}>{pct}%</span>}
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  총 {total}표
                  {!post.is_mine && post.ap_id && (
                    <button
                      type="button"
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (pollRefreshing) return;
                        setPollRefreshing(true);
                        try {
                          const result = await api.refreshPoll(post.id);
                          if (result.post) Object.assign(post, result.post);
                          if (onUpdate) onUpdate();
                          else window.dispatchEvent(new Event("postchange"));
                        } catch (err: any) { alert(err.message); }
                        finally { setPollRefreshing(false); }
                      }}
                      className="action-btn"
                      style={{ fontSize: 10, padding: "1px 4px", lineHeight: 1 }}
                      title="원격 서버에서 최신 투표 결과 가져오기"
                    >
                      <span style={pollRefreshing ? { animation: "spin 1s linear infinite" } : undefined}><Icon name="refresh" /></span>
                    </button>
                  )}
                </span>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {!showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(true); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>결과 보기</button>
                  )}
                  {showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(false); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>투표하기</button>
                  )}
                  {post.poll_data!.expires_at ? (
                    new Date(post.poll_data!.expires_at).getTime() < now ? <span>종료</span> : <span>{formatRelative(post.poll_data!.expires_at, now)}</span>
                  ) : null}
                </span>
              </div>
            </div>;
          })()
        )}
        {loadingQuote && <div className="empty-small loading-small">인용 불러오는 중...</div>}
        {quotedPost && <div className="my-8"><MiniPostCard post={quotedPost} /></div>}
        {quotedSeries && (
          <div className="quoted-series" onClick={(e) => { e.stopPropagation(); router.push(`/series/${quotedSeries.novel.id}`); }}>
              <div className="cover-wrap-64 bg-tertiary">
              {quotedSeries.novel.cover_image ? (
                <ClickableCover src={quotedSeries.novel.cover_image} isSensitive={(quotedSeries.novel as any).is_sensitive} className="cover-img" />
              ) : (
                (window as any).__serverLogo ? <img src={(window as any).__serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
                : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedSeries.novel.title) }}>
                  {quotedSeries.novel.title[0]}
                </div>
              )}
            </div>
            <div className="mini-post-content">
              <div className="mini-post-cw"><Icon name="book" /> 시리즈</div>
              <div className="emoji-keyword">{quotedSeries.novel.title}</div>
              {quotedSeries.author && <div className="text-sm text-muted">by {quotedSeries.author.display_name || quotedSeries.author.username}</div>}
              {quotedSeries.novel.description && <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedSeries.novel.description.slice(0, 100)}</div>}
            </div>
          </div>
        )}
        {quotedEpisode && (
          <div className="quoted-series" onClick={(e) => { e.stopPropagation(); router.push(`/series/${quotedEpisode.novel.id}/episodes/${quotedEpisode.episode.id}`); }}>
            <div className="cover-wrap-64 bg-tertiary">
              {quotedEpisode.novel.cover_image ? (
                <ClickableCover src={quotedEpisode.novel.cover_image} isSensitive={(quotedEpisode.novel as any).is_sensitive} className="cover-img" />
              ) : (
                (window as any).__serverLogo ? <img src={(window as any).__serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
                : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedEpisode.novel.title) }}>
                  {quotedEpisode.novel.title[0]}
                </div>
              )}
            </div>
            <div className="mini-post-content">
              <div className="mini-post-cw"><Icon name="book" /> 에피소드</div>
              <div className="emoji-keyword">{quotedEpisode.novel.title} — {quotedEpisode.episode.title}</div>
              {quotedEpisode.author && <div className="text-sm text-muted">by {quotedEpisode.author.display_name || quotedEpisode.author.username}</div>}
              {quotedEpisode.episode.summary ? (
                <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.summary}</div>
              ) : (
                <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").slice(0, 50)}{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").length > 50 ? "..." : ""}</div>
              )}
            </div>
          </div>
        )}
        {!post.summary && post.link_preview && !(post as any).quote_of_id && !(post as any).quote_of_ap_id && (() => {
            const lp = post.link_preview!;
            const isLocalLink = (() => { try { return new URL(lp.url).hostname === window.location.hostname; } catch { return false; } })();
            const lpImage = isLocalLink ? ((window as any).__serverLogo || lp.image) : lp.image;
            return (
          <a href={lp.url} target="_blank" rel="noopener noreferrer" className="link-preview-card" onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 12, marginTop: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
            {lpImage && <img src={lpImage} alt="" style={{ width: 80, height: 80, borderRadius: isLocalLink ? 16 : 6, objectFit: "contain", flexShrink: 0, background: isLocalLink ? "var(--bg-tertiary)" : undefined }} onError={(e) => (e.target as HTMLElement).style.display = "none"} />}
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lp.title}</div>
              {lp.description && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{lp.description}</div>}
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{(() => { try { return new URL(lp.url).hostname; } catch { return ""; } })()}</div>
            </div>
          </a>
            );
          })()}
        {reactions && Object.keys(reactions).length > 0 && currentUser?.enable_reactions !== false && (
          <div className="reactions-row" style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8, marginBottom: 4, padding: "0 8px" }} onClick={(e) => e.stopPropagation()}>
            {Object.entries(reactions).sort(([a], [b]) => a === "★" ? -1 : b === "★" ? 1 : 0).map(([emoji, count]) => {

              const emojiKey = emoji.startsWith(":") && emoji.endsWith(":") ? emoji.slice(1, -1) : emoji;
              const isCustomEmoji = emoji.startsWith(":") && emoji.endsWith(":");

              const isMapLoaded = Object.keys(reactionEmojiMap).length > 0;
              const emojiIsRemote = isCustomEmoji && isMapLoaded && !localReactionEmojiMap[emojiKey];
              return (
                <span
                  key={emoji}
                   className={`reaction-badge${myReaction === emoji ? " active" : ""}`}
                  onClick={async () => {
                    // 💡 원격 에모지라면 클릭 시 즉시 리턴하여 백엔드 요청을 방어합니다.
                    if (emojiIsRemote) return;
                    if (myReaction === emoji) {
                      const next = { ...reactions };
                      if (next[emoji] <= 1) delete next[emoji];
                      else next[emoji] -= 1;
                      setReactions(next);
                      setMyReaction(null);
                      setLiked(false);
                      setLikesCount(Math.max(0, likesCount - 1));
                      try {
                        await api.unreact(post.id);
                      } catch {}
                    } else {
                      const next = { ...reactions };
                      if (myReaction && myReaction !== emoji) {
                        if ((next[myReaction] || 0) <= 1) delete next[myReaction];
                        else next[myReaction] -= 1;
                      }
                      next[emoji] = (next[emoji] || 0) + 1;
                      setReactions(next);
                      setMyReaction(emoji);
                      setLiked(true);
                      setLikesCount(myReaction ? likesCount : likesCount + 1);
                      try {
                        await api.react(post.id, emoji);
                      } catch {}
                    }
                  }}
                  style={{ 
                    display: "inline-flex", 
                    alignItems: "center", 
                    gap: 3, 
                    padding: "2px 8px", 
                    borderRadius: 12, 
                    fontSize: 13, 
                    cursor: emojiIsRemote ? "default" : "pointer", // 원격이면 커서 기본값
                    border: "1px solid var(--border)", 
                    background: myReaction === emoji ? "color-mix(in srgb, var(--accent) 20%, transparent)" : "var(--bg-secondary)", 
                    opacity: 1
                  }}
                >
                  {emoji === "★" ? (
                    <Icon name="star_filled" size={18} style={{ color: "#f1c40f" }} />
                  ) : isCustomEmoji ? (
                    reactionEmojiMap[emojiKey]
                      ? <img src={reactionEmojiMap[emojiKey]} alt={emoji} style={{ height: 22, verticalAlign: "middle" }} />
                      : <span>{emoji}</span>
                  ) : (
                    <span>{emoji}</span>
                  )}
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{count}</span>
                </span>
              );
            })}
          </div>
        )}
        {!readonly && <div className="post-actions" onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setShowReply(!showReply); }} className="action-btn">
            <Icon name="reply" /> {post.replies_count}
          </button>
          <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
            <button type="button" onClick={toggleBoost} disabled={!post.is_mine && (post.visibility === "followers" || post.visibility === "mention")} className={`action-btn ${boosted ? "boosted" : ""}`}>
              <Icon name="refresh" /> {boostsCount}
            </button>
          </form>
          {currentUser?.enable_reactions !== false ? (
            <span onClick={(e) => e.stopPropagation()} className="relative-wrap" style={{ marginBottom: -2 }}>
              <EmojiPicker onEmoji={async (emoji) => {
                const next = { ...reactions };
                if (myReaction && myReaction !== emoji) {
                  if ((next[myReaction] || 0) <= 1) delete next[myReaction];
                  else next[myReaction] -= 1;
                }
                next[emoji] = (next[emoji] || 0) + 1;
                setReactions(next);
                setMyReaction(emoji);
                setLiked(true);
                setLikesCount(myReaction ? likesCount : likesCount + 1);
                try {
                  await api.react(post.id, emoji);
                } catch {}
              }} />
            </span>
          ) : (
            <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
              <button type="button" onClick={toggleLike} className={`action-btn ${liked ? "liked" : ""}`}>
                <Icon name={myReaction && liked ? "star_filled" : liked ? "star_filled" : "star"} /> {likesCount}
              </button>
            </form>
          )}
          <button onClick={(e) => { e.stopPropagation(); toggleBookmark(); }} className={`action-btn${bookmarked ? " bookmarked" : ""}`} style={{ color: bookmarked ? "#5b7db5" : undefined }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill={bookmarked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
          </button>
          {(post.is_mine || currentUser?.is_admin || currentUser && !post.is_mine) && (
            <div className="post-actions-more" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => setShowMoreActions(!showMoreActions)} className="action-btn post-actions-more-btn">
                <Icon name="more_horizontal" />
              </button>
              {showMoreActions && (
                <div className="post-actions-dropdown">
                  <ShareButton url={post.ap_id?.startsWith("http") ? post.ap_id : (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`)} className="post-actions-dropdown-item" />
                  {post.is_mine && (
                    <button onClick={() => { setShowMoreActions(false); (async () => {
                      const newPinned = !pinned;
                      setPinned(newPinned);
                      const res = await fetch(`/api/${newPinned ? "pin" : "unpin"}/post/${post.id}`, { method: "POST", credentials: "include" });
                      if (!res.ok) { setPinned(!newPinned); const d = await res.json().catch(() => ({})); if (d.detail) alert(d.detail); }
                      else { window.dispatchEvent(new Event("pinchange")); window.dispatchEvent(new Event("profilechange")); }
                    })(); }} className="post-actions-dropdown-item">
                      <Icon name={pinned ? "pin_filled" : "pin"} /> {pinned ? "고정 해제" : "고정"}
                    </button>
                  )}
                  {post.is_mine && (
                    <button onClick={() => { setShowMoreActions(false); setShowEdit(true); }} className="post-actions-dropdown-item">
                      <Icon name="edit" /> 수정
                    </button>
                  )}
                  {post.is_mine && (
                    <button onClick={async () => {
                      setShowMoreActions(false);
                      const stripped = (post.content || "").replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
                      try { await api.deletePost(post.id); } catch {}
                      if (onDelete) onDelete();
                      else if (onUpdate) onUpdate();
                      if (onRewrite) onRewrite(stripped, post.visibility, post.reply_context);
                      else setShowRewrite(true);
                    }} className="post-actions-dropdown-item">
                      <Icon name="trash" /> 지우고 다시 쓰기
                    </button>
                  )}
                  {(post.is_mine || currentUser?.is_admin) && (
                    <button onClick={() => { setShowMoreActions(false); handleDelete(); }} className="post-actions-dropdown-item post-actions-dropdown-danger">
                      <Icon name="trash" /> 삭제
                    </button>
                  )}
                  {currentUser && !post.is_mine && (
                    <button onClick={() => { setShowMoreActions(false); setShowReport(true); setReportReason(""); setReportError(""); setReportDone(false); setSelectedRuleIds([]); fetch("/api/rules").then(r => r.json()).then(setReportRules).catch(() => {}); }} className="post-actions-dropdown-item">
                      <Icon name="flag" /> 신고
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>}
      </div>
      {!readonly && showReply && <ReplyModal post={post} onClose={() => setShowReply(false)} onDone={(newPost) => { setShowReply(false); if (onReply) onReply(newPost); else if (onUpdate) onUpdate(); }} />}
      {!readonly && showEdit && <EditModal post={post} onClose={() => setShowEdit(false)} onDone={(updated) => { setShowEdit(false); if (onUpdate) onUpdate(updated); }} />}
      {!readonly && showReport && (
        <div className="reply-modal-backdrop active" onClick={() => setShowReport(false)}>
          <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <button className="reply-modal-close" onClick={() => setShowReport(false)}>×</button>
            <h3>게시글 신고</h3>
            {reportDone ? (
              <p style={{ color: "var(--text-secondary)", margin: "16px 0" }}>신고가 접수되었습니다. 검토 후 조치하겠습니다.</p>
            ) : (
              <>
                {reportRules.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--text-secondary)" }}>위반 규칙</p>
                    {reportRules.map((rule) => (
                      <label key={rule.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", marginBottom: 4, borderRadius: 6, border: selectedRuleIds.includes(rule.id) ? "1px solid var(--accent)" : "1px solid var(--border)", background: selectedRuleIds.includes(rule.id) ? "var(--bg-tertiary)" : "var(--bg-secondary)", cursor: "pointer", transition: "all 0.15s" }}>
                        <input type="checkbox" checked={selectedRuleIds.includes(rule.id)} onChange={(e) => setSelectedRuleIds((prev) => e.target.checked ? [...prev, rule.id] : prev.filter((id) => id !== rule.id))} style={{ marginTop: 2, accentColor: "var(--accent)" }} />
                        <span style={{ fontSize: 13, color: "var(--text)" }}><strong>{rule.title}</strong>{rule.description ? <span style={{ color: "var(--text-secondary)" }}>{` — ${rule.description}`}</span> : ""}</span>
                      </label>
                    ))}
                  </div>
                )}
                <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: "var(--text-secondary)" }}>기타 사유</p>
                <textarea
                  value={reportReason}
                  onChange={(e) => setReportReason(e.target.value)}
                  placeholder={selectedRuleIds.length > 0 ? "추가 사유 (선택)" : "신고 사유를 입력해주세요 (최소 10자)"}
                  style={{ width: "100%", minHeight: 80, resize: "vertical", marginBottom: 8 }}
                />
                {reportError && <p style={{ color: "var(--error)", fontSize: 14, marginBottom: 8 }}>{reportError}</p>}
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 8, color: "var(--text-secondary)", cursor: "pointer" }}>
                  <input type="checkbox" checked={reportForward} onChange={(e) => setReportForward(e.target.checked)} />
                  원격 서버로 신고 전송
                </label>
                <button onClick={handleReport} className="btn" style={{ width: "100%" }}>신고 제출</button>
              </>
            )}
          </div>
        </div>
      )}
      {viewerIndex >= 0 && (post as any).media_attachments?.length > 0 && (
        <div className="reply-modal-backdrop active" onClick={() => { setViewerZoom(1); setViewerPan({ x: 0, y: 0 }); setViewerIndex(-1); }}>
          <div className="media-viewer" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "90vw", maxHeight: "90vh", display: "flex", alignItems: "center", justifyContent: "center", position: "relative", overflow: "hidden", cursor: viewerZoom > 1 ? "grab" : "default", touchAction: "none" }}
            onWheel={handleViewerWheel}
            onTouchStart={handleViewerTouchStart}
            onTouchMove={handleViewerTouchMove}
            onTouchEnd={handleViewerTouchEnd}
            onMouseDown={handleViewerMouseDown}
            onMouseMove={handleViewerMouseMove}
            onMouseUp={handleViewerMouseUp}
            onMouseLeave={handleViewerMouseUp}
          >
            {(viewerIndex > 0) && (
              <button onClick={(e) => { e.stopPropagation(); setViewerIndex(viewerIndex - 1); }} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20, color: "#fff" }}>‹</button>
            )}
            {(viewerIndex < (post as any).media_attachments.length - 1) && (
              <button onClick={(e) => { e.stopPropagation(); setViewerIndex(viewerIndex + 1); }} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20, color: "#fff" }}>›</button>
            )}
            <button onClick={(e) => { e.stopPropagation(); setViewerZoom(1); setViewerPan({ x: 0, y: 0 }); setViewerIndex(-1); }} style={{ position: "absolute", top: 8, right: 8, background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 22, cursor: "pointer", zIndex: 10 }}>×</button>
            {viewerZoom > 1 && <div style={{ position: "absolute", top: 8, left: 8, background: "rgba(0,0,0,0.5)", color: "#fff", borderRadius: 12, padding: "2px 10px", fontSize: 12, zIndex: 10, userSelect: "none" }}>{Math.round(viewerZoom * 100)}%</div>}
            {(() => {
              const m = (post as any).media_attachments[viewerIndex];
              return m?.type === "video" ? (
                <video src={m.url} controls style={{ maxWidth: "100%", maxHeight: "85vh", borderRadius: 8 }} />
              ) : (
                <img ref={viewerImgRef} src={m.url} alt={m.alt || ""} draggable={false} onDoubleClick={handleViewerDblClick} style={{ maxWidth: viewerZoom > 1 ? "none" : "100%", maxHeight: viewerZoom > 1 ? "none" : "85vh", borderRadius: viewerZoom > 1 ? 0 : 8, objectFit: "contain", transform: `scale(${viewerZoom}) translate(${viewerPan.x / viewerZoom}px, ${viewerPan.y / viewerZoom}px)`, transition: isPanning.current ? "none" : "transform 0.15s ease", userSelect: "none" }} />
              );
            })()}
          </div>
        </div>
      )}
      {!readonly && showRewrite && post.reply_context && (
        <ReplyModal post={{
          id: post.reply_context.id,
          number: post.reply_context.number,
          content: post.reply_context.content,
          author: post.reply_context.author,
          visibility: post.reply_context.visibility,
          summary: null,
          created_at: null,
          ap_id: "",
          likes_count: 0,
          boosts_count: 0,
          replies_count: 0,
          liked: false,
          boosted: false,
          bookmarked: false,
          is_mine: false,
          reply_context: null,
          media_attachments: [],
        } as any} onClose={() => setShowRewrite(false)} onDone={(newPost) => {
          setShowRewrite(false);
          if (onUpdate) onUpdate();
        }} />
      )}
      {!readonly && showRewrite && !post.reply_context && (
        <div className="reply-modal-backdrop active" onClick={() => setShowRewrite(false)}>
          <div className="reply-modal modal-form" onClick={(e) => e.stopPropagation()}>
            <button className="reply-modal-close" onClick={() => setShowRewrite(false)}>×</button>
            <h3>지우고 다시 쓰기</h3>
            <PostForm onDone={(newPost) => {
              setShowRewrite(false);
            }} initialContent={(post.content || "").replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'")} initialVisibility={post.visibility} />
          </div>
        </div>
      )}
    </>
  );
}


