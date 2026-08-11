"use client";
import { PostData, User, ReplyContext, api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useState, useEffect, useMemo, useRef } from "react";
import { injectEmojis, renderCustomEmojis, useEmojiList, CustomEmoji } from "@/lib/emojis";
import { sanitizePost, sanitizeName } from "@/lib/sanitize";
import { installCodeCopyButtons } from "@/lib/codeCopy";
import { getQuote } from "@/lib/quote-cache";
import { useAuth } from "@/lib/auth";
import { useReactions } from "@/lib/useReactions";
import { useNow } from "@/hooks/useNow";
import { buildPostContentHtml } from "@/lib/postContent";
import { WindowWithGlobals } from "@/lib/windowGlobals";
import Icon from "./Icon";
import MediaViewer from "./MediaViewer";
import EditModal from "./EditModal";
import ReplyModal from "./ReplyModal";
import PostHeader from "./PostHeader";
import ReplyContextBox from "./ReplyContextBox";
import MediaGallery from "./MediaGallery";
import LinkPreviewCard from "./LinkPreviewCard";
import PollBox from "./PollBox";
import QuotedCard, { QuotedSeries, QuotedEpisode } from "./QuotedCard";
import ReactionsRow from "./ReactionsRow";
import PostActions from "./PostActions";
import ReportModal from "./ReportModal";
import RewriteModal from "./RewriteModal";

const PostCard = React.memo(function PostCard({ post, onUpdate, onDelete, onReply, onRewrite, current, hideContext, selected, readonly, mentionBy }: { post: PostData; onUpdate?: (updated?: PostData) => void; onDelete?: () => void; onReply?: (newPost?: PostData) => void; onRewrite?: (content: string, visibility: string, summary: string, replyTo?: ReplyContext | null, media?: { url: string; type: string; alt?: string }[]) => void; current?: boolean; hideContext?: boolean; selected?: boolean; readonly?: boolean; mentionBy?: User | null }) {
  const router = useRouter();
  const { user: currentUser } = useAuth();
  const [showReply, setShowReply] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [showRewrite, setShowRewrite] = useState(false);
  const [rewriteContent, setRewriteContent] = useState<string | null>(null);
  const [rewriteSummary, setRewriteSummary] = useState<string>("");
  const [rewriteMedia, setRewriteMedia] = useState<{ url: string; type: string; alt?: string }[]>([]);
  const [pinned, setPinned] = useState(false);
  const [boosted, setBoosted] = useState(post.boosted);
  const [bookmarked, setBookmarked] = useState(post.bookmarked);
  const [boostsCount, setBoostsCount] = useState(post.boosts_count);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [seriesMatch, setSeriesMatch] = useState<RegExpMatchArray | null>(null);
  const [episodeMatch, setEpisodeMatch] = useState<RegExpMatchArray | null>(null);
  const [quotedPost, setQuotedPost] = useState<PostData | null>(null);
  const [quotedSeries, setQuotedSeries] = useState<QuotedSeries | null>(null);
  const [quotedEpisode, setQuotedEpisode] = useState<QuotedEpisode | null>(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [viewerIndex, setViewerIndex] = useState(-1);
  const [revealedSensitive, setRevealedSensitive] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const quoteAttemptedUrlRef = useRef<string | null>(null);

  const targetId = post.boost_of_id || post.id;

  const emojiList = useEmojiList();
  const { liked, likesCount, reactions, myReaction, toggleLike, reactTo, unreact } = useReactions(post, targetId);

  const reactionEmojiMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const e of emojiList) if (e.keyword && e.url) map[e.keyword] = e.url;
    const cached = (window as WindowWithGlobals).__emojiMap;
    if (cached) {
      for (const [k, v] of Object.entries(cached)) if (!map[k] && v) map[k] = v;
    }
    (window as WindowWithGlobals).__emojiMap = map;
    return map;
  }, [emojiList]);
  const localReactionEmojiMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const e of emojiList) {
      if (e.keyword && e.url && e.url.includes('/emojis/local/')) {
        map[e.keyword] = e.url;
      }
    }
    const cached = (window as WindowWithGlobals).__localEmojiMap;
    if (cached) {
      for (const [k, v] of Object.entries(cached)) if (!map[k] && v) map[k] = v;
    }
    (window as WindowWithGlobals).__localEmojiMap = map;
    return map;
  }, [emojiList]);

  useEffect(() => {
    if (currentUser?.pinned_posts) setPinned(currentUser.pinned_posts.includes(post.id));
  }, [currentUser, post.id]);

  const postIdRef = useRef(post.id);
  useEffect(() => {
    if (postIdRef.current !== post.id) {
      postIdRef.current = post.id;
      setBoosted(post.boosted);
      setBookmarked(post.bookmarked);
    }
  }, [post.id, post.boosted, post.bookmarked]);
  useEffect(() => {
    setBoostsCount(post.boosts_count);
  }, [post.boosts_count]);

  const toggleBookmark = () => {
    const next = !bookmarked;
    setBookmarked(next);
    (next ? api.bookmark(targetId) : api.unbookmark(targetId)).catch(() => {
      setBookmarked(!next);
    });
  };

  const toggleBoost = async () => {
    if (!boosted && (post.visibility === "mention" || (!post.is_mine && post.visibility === "followers"))) return;
    const prevCount = boostsCount;
    try {
      if (boosted) {
        setBoosted(false);
        setBoostsCount(Math.max(0, boostsCount - 1));
        await api.unboost(targetId);
      }
      else {
        setBoosted(true);
        setBoostsCount(boostsCount + 1);
        await api.boost(targetId);
      }
    } catch {
      setBoosted(false);
      setBoostsCount(prevCount);
    }
  };

  const handleDelete = async () => {
    const isAdminDeletingOther = currentUser?.is_admin && !post.is_mine;
    if (!confirm(isAdminDeletingOther ? "관리자 권한으로 이 게시글을 삭제하시겠습니까?" : "삭제하시겠습니까?")) return;
    try {
      await api.deletePost(post.id);
    } catch {
      alert("삭제에 실패했습니다. 다시 시도해주세요.");
      return;
    }
    if (onDelete) onDelete();
    else if (onUpdate) onUpdate();
    else if (current) router.back();
  };

  const mergedEmojiList = useMemo(() => {
    if (!post._emojis || post._emojis.length === 0) return emojiList;
    // 같은 키워드 충돌 시 이 글의 _emojis(작성자 도메인 기준)를 우선한다.
    const map = new Map<string, CustomEmoji>();
    for (const e of post._emojis) {
      if (e.keyword && e.url) map.set(e.keyword, { ...e, category: "remote" });
    }
    for (const e of emojiList) {
      if (!map.has(e.keyword)) map.set(e.keyword, e);
    }
    return Array.from(map.values());
  }, [emojiList, post._emojis]);

  useEffect(() => {
    if (post._emojis) injectEmojis(post._emojis);
  }, [post._emojis]);

  // contentHtml: emojiList 변경 시 즉시 재계산하여 이모지 렌더링 깜빡임 방지
  const contentHtml = useMemo(() => sanitizePost(buildPostContentHtml(post, mergedEmojiList)), [post, mergedEmojiList]);

  // 코드 복사 버튼 플러그인 Effect
  useEffect(() => {
    if (cardRef.current) installCodeCopyButtons(cardRef.current);
  }, [contentHtml, post.content]);

  // series/episode 매칭 추출용 Effect
  useEffect(() => {
    const rawContent = post.content || "";
    const base = typeof window !== "undefined" ? window.location.host : "";
    const baseDomain = base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // 기존: series:/episode: 접두사 패턴
    const seriesMatches = rawContent.match(/(?:<br\s*\/?>|\n|^)\s*(series):\s*(?:<a[^>]*href="([^"]+)"[^>]*>.*?<\/a>|(https?:\/\/[^\s<>]+))/i);
    const episodeMatches = rawContent.match(/(?:<br\s*\/?>|\n|^)\s*(episode):\s*(?:<a[^>]*href="([^"]+)"[^>]*>.*?<\/a>|(https?:\/\/[^\s<>]+))/i);
    setSeriesMatch(seriesMatches && (seriesMatches[2] || seriesMatches[3]) ? seriesMatches : null);
    setEpisodeMatch(episodeMatches && (episodeMatches[2] || episodeMatches[3]) ? episodeMatches : null);
    // 확장: 본문에서 접두사 없는 시리즈/에피소드 URL도 감지
    let epUrl: RegExpMatchArray | null = null;
    let serUrl: RegExpMatchArray | null = null;
    if (!seriesMatches && !episodeMatches) {
      epUrl = rawContent.match(new RegExp(`https?://${baseDomain}/series/(?:@[^/]+/)?(\\d+)/episodes/(\\d+)`, "i"));
      serUrl = rawContent.match(new RegExp(`https?://${baseDomain}/series/(?:@[^/]+/)?(\\d+)(?!/episodes)`, "i"));
      if (epUrl) {
        setEpisodeMatch(Object.assign([epUrl[0], epUrl[0]], { 0: epUrl[0], index: 0 }) as RegExpMatchArray);
      } else if (serUrl) {
        setSeriesMatch(Object.assign([serUrl[0], serUrl[0]], { 0: serUrl[0], index: 0 }) as RegExpMatchArray);
      }
    }
    // 확장: 본문에서 로컬 포스트 URL 감지 → quote_of_id가 없을 때 자동 로드
    // NOTE: 로컬 변수로 시리즈/에피소드 매칭 여부 판단 (클로저 stale 방지)
    const hasSeriesEpisodeMatch = !!(seriesMatches || episodeMatches || epUrl || serUrl);
    if (!post.quote_of_id && !post.quote_of_ap_id && !hasSeriesEpisodeMatch) {
      const localPostMatch = rawContent.match(new RegExp(`https?://${baseDomain}/@([^/]+)/(\\d+)`, "i"));
      if (localPostMatch && !loadingQuote && !quotedPost) {
        setLoadingQuote(true);
        const username = localPostMatch[1];
        const number = localPostMatch[2];
        getQuote(`bynum:${username}/${number}`, () =>
          fetch(`/api/by-number/${username}/${number}`, { credentials: "include" })
            .then(r => { if (r.ok) return r.json(); throw new Error(); })
        )
          .then(d => {
            if (d) { if (d._emojis) injectEmojis(d._emojis); setQuotedPost(d); }
          })
          .finally(() => setLoadingQuote(false));
      }
    }
  }, [post, loadingQuote, quotedPost]);

  // Handle stored quote reference from ActivityPub (quote_of_id / quote_of_ap_id)
  useEffect(() => {
    if (quotedPost || quotedSeries || quotedEpisode || loadingQuote) return;
    const embedded = post.quoted_post;
    if (embedded && embedded.id && embedded.author) {
      if (embedded._emojis) injectEmojis(embedded._emojis);
      setQuotedPost(embedded);
      return;
    }
    const qid = post.quote_of_id;
    const qApId = post.quote_of_ap_id;
    if (qid) {
      setLoadingQuote(true);
      getQuote(`id:${qid}`, () => api.getPost(qid, 0, 0, 0, 0).catch(() => null))
        .then(d => { if (d) { if (d._emojis) injectEmojis(d._emojis); setQuotedPost(d); } })
        .finally(() => setLoadingQuote(false));
    } else if (qApId) {
      setLoadingQuote(true);
      const form = new FormData(); form.append("url", qApId);
      getQuote(`url:${qApId}`, () =>
        fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form })
          .then(r => { if (r.ok) return r.json(); throw new Error(); })
          .catch(() => null)
      )
        .then(d => { if (d) { if (d._emojis) injectEmojis(d._emojis); setQuotedPost(d); } })
        .finally(() => setLoadingQuote(false));
    }
  }, [post, loadingQuote, quotedPost, quotedSeries, quotedEpisode]);

  // Detect series/episode share URLs in content (e.g. "series: https://.../series/123")
  useEffect(() => {
    // 🌟 [추가] 중요: 포스트가 새로 바뀌었을 때(또는 주소가 없을 때) 이전 포스트의 카드 데이터를 초기화합니다.
    const match = seriesMatch || episodeMatch;
    if (!match) {
      setQuotedSeries(null);
      setQuotedEpisode(null);
      quoteAttemptedUrlRef.current = null;
      return;
    }

    if (loadingQuote) return;

    const url = typeof match === 'string' ? match : (match[2] || match[3] || match[0]);
    if (!url) return;
    // 🌟 이미 시도한 URL이면(성공/실패 무관) 재시도하지 않는다.
    // loadingQuote가 의존성에 있어 fetch 완료 후 setLoadingQuote(false)가 이펙트를 재실행시키므로,
    // 가드가 없으면 같은 주소를 무한히 refetch하게 된다.
    if (quoteAttemptedUrlRef.current === url) return;
    quoteAttemptedUrlRef.current = url;
    setQuotedSeries(null);
    setQuotedEpisode(null);
    // 🌟 [정규식 수정] 실제 주소 스펙에 맞춤
    // 1. 에피소드 주소 (ex: /series/1/episodes/5)
    const epMatch = url.match(/\/series\/(?:@[^/]+\/)?(\d+)\/episodes\/(\d+)/);
    // 2. 시리즈 단독 주소 (ex: /series/1, /series/@user/1)
    const seriesOnlyMatch = url.match(/\/series\/(?:by-number\/[^/]+\/|@[^/]+\/)?([a-zA-Z0-9]+)(?:\?.*)?$/);
    if (epMatch) {
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
  }, [post.id, seriesMatch, episodeMatch, loadingQuote]);

  useEffect(() => {
    const onOpenMedia = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d && d.postId && d.postId !== post.id) return;
      const media = post.media_attachments || [];
      if (!media.length) return;
      setRevealedSensitive(true);
      setViewerIndex(d && typeof d.index === "number" ? d.index : 0);
    };
    const onReveal = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d && d.postId && d.postId !== post.id) return;
      setRevealedSensitive(true);
    };
    window.addEventListener("writ:open-media", onOpenMedia);
    window.addEventListener("writ:reveal-post", onReveal);
    return () => {
      window.removeEventListener("writ:open-media", onOpenMedia);
      window.removeEventListener("writ:reveal-post", onReveal);
    };
  }, [post]);

  useEffect(() => {
    if (!showMoreActions) return;
    const handler = () => setShowMoreActions(false);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [showMoreActions]);

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

  const nowTime = useNow();
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

  const remoteUrl = (() => {
    const u = post.url || post.ap_id || "";
    if (!u) return "";
    const m = u.match(/^(https?:\/\/[^/]+)\/users\/([^/]+)\/statuses\/(\d+)$/);
    return m ? `${m[1]}/@${m[2]}/${m[3]}` : u;
  })();

  const postHref = post.boost_of_id
    ? (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.boost_of_id}`)
    : (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`);

  const handleTogglePin = () => {
    const newPinned = !pinned;
    setPinned(newPinned);
    (async () => {
      const res = await fetch(`/api/${newPinned ? "pin" : "unpin"}/post/${targetId}`, { method: "POST", credentials: "include" });
      if (!res.ok) { setPinned(!newPinned); const d = await res.json().catch(() => ({})); if (d.detail) alert(d.detail); }
      else { window.dispatchEvent(new Event("pinchange")); window.dispatchEvent(new Event("profilechange")); }
    })();
  };

  const handleRewrite = async () => {
    const stripped = (post.content || "").replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    const media = (post.media_attachments || []).map((m) => ({ url: m.url, type: m.type || "image", alt: m.alt || "" }));
    try {
      await api.deletePost(post.id, true);
    } catch {
      alert("삭제에 실패했습니다. 다시 시도해주세요.");
      return;
    }
    if (onDelete) onDelete();
    else if (onUpdate) onUpdate();
    if (onRewrite) onRewrite(stripped, post.visibility, post.summary || "", post.reply_context, media);
    else { setRewriteContent(stripped); setRewriteSummary(post.summary || ""); setRewriteMedia(media); setShowRewrite(true); }
  };

  const closeRewrite = () => {
    setShowRewrite(false);
    setRewriteContent(null);
    setRewriteSummary("");
    setRewriteMedia([]);
  };

  const handleToggleReaction = (emoji: string) => {
    if (myReaction === emoji) unreact(emoji);
    else reactTo(emoji);
  };

  if (!post || !post.author) return null;

  const postSensitive = post.is_sensitive || post.author.is_sensitive || !!post.summary;
  const mediaGallery = (sensitive: boolean) => (
    <MediaGallery media={post.media_attachments || []} sensitive={sensitive} revealed={revealedSensitive} onReveal={() => setRevealedSensitive(true)} onHide={() => setRevealedSensitive(false)} onOpen={(i) => setViewerIndex(i)} />
  );

  return (
    <>
      <div ref={cardRef} className={`post-card${current ? " current" : ""}${selected ? " selected" : ""}${post.visibility === "mention" ? " mention-card" : ""}`}>
        {post.boosted_by && post.boosted_by.length > 0 && (
          <div className="boost-badge">
            <Icon name="refresh" size={12} /> <Link href={`/@${post.boosted_by[0].username}`}><span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.boosted_by[0].display_name || post.boosted_by[0].username, mergedEmojiList, 14)) }} /></Link>님이 부스트
          </div>
        )}
        {mentionBy && (
          <div className="boost-badge">
            <Icon name="mention" size={12} /> <Link href={`/@${mentionBy.username}`}><span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(mentionBy.display_name || mentionBy.username, mergedEmojiList, 14)) }} /></Link>님이 멘션
          </div>
        )}
        <PostHeader post={post} mergedEmojiList={mergedEmojiList} timeStr={timeStr} postHref={postHref} />
        {!hideContext && post.reply_context && (
          <ReplyContextBox post={post} mergedEmojiList={mergedEmojiList} />
        )}
        {post.summary ? (
          <details className="cw-box">
            <summary onClick={(e) => e.stopPropagation()} dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(post.summary, mergedEmojiList)) }} />
            <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
            {(post.media_attachments?.length ?? 0) > 0 && mediaGallery(postSensitive)}
            {post.link_preview && !post.quote_of_id && !post.quote_of_ap_id && !seriesMatch && !episodeMatch && <LinkPreviewCard lp={post.link_preview} />}
          </details>
        ) : (() => {
          const textOnly = (post.content || "").replace(/<[^>]+>/g, "").replace(/&[^;]+;/g, "x");
          const lineCount = textOnly.split("\n").length;
          const isLong = lineCount > 10 || textOnly.length > 1000;
          if (!isLong) {
            return <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />;
          }
          return (
            <div className={`post-content-wrap${expanded ? " expanded" : ""}`}>
              <div className="post-content" onClick={handleContentClick} dangerouslySetInnerHTML={{ __html: contentHtml }} />
              {!expanded && <div className="post-expand-overlay" onClick={(e) => { e.stopPropagation(); setExpanded(true); }}>
                <button className="post-expand-btn" onClick={(e) => { e.stopPropagation(); setExpanded(true); }}>더 보기</button>
              </div>}
              {expanded && <div className="post-collapse-bar" onClick={(e) => { e.stopPropagation(); setExpanded(false); }}>
                <button className="post-collapse-btn" onClick={(e) => { e.stopPropagation(); setExpanded(false); }}>접기</button>
              </div>}
            </div>
          );
        })()}
        {!post.summary && (post.media_attachments?.length ?? 0) > 0 && mediaGallery(postSensitive)}
        {post.poll_data && <PollBox post={post} targetId={targetId} readonly={readonly} onUpdate={onUpdate} />}
        {loadingQuote && <div className="empty-small loading-small">인용 불러오는 중...</div>}
        <QuotedCard quotedPost={quotedPost} quotedSeries={quotedSeries} quotedEpisode={quotedEpisode} onNavigate={(href) => router.push(href)} />
        {!post.summary && post.link_preview && !post.quote_of_id && !post.quote_of_ap_id && !seriesMatch && !episodeMatch && <LinkPreviewCard lp={post.link_preview} />}
        {reactions && Object.keys(reactions).length > 0 && currentUser?.enable_reactions !== false && (
          <ReactionsRow reactions={reactions} myReaction={myReaction} onToggle={handleToggleReaction} targetId={targetId} emojiMap={reactionEmojiMap} localEmojiMap={localReactionEmojiMap} />
        )}
        {!readonly && (
          <PostActions
            post={post}
            currentUser={currentUser}
            liked={liked}
            likesCount={likesCount}
            myReaction={myReaction}
            boosted={boosted}
            boostsCount={boostsCount}
            bookmarked={bookmarked}
            pinned={pinned}
            showMoreActions={showMoreActions}
            remoteUrl={remoteUrl}
            onReply={() => setShowReply(!showReply)}
            onToggleLike={toggleLike}
            onToggleBoost={toggleBoost}
            onToggleBookmark={toggleBookmark}
            onReact={reactTo}
            onToggleMore={() => setShowMoreActions(!showMoreActions)}
            onTogglePin={handleTogglePin}
            onEdit={() => setShowEdit(true)}
            onRewrite={handleRewrite}
            onDelete={handleDelete}
            onReport={() => setShowReport(true)}
          />
        )}
      </div>
      {!readonly && showReply && <ReplyModal post={post} onClose={() => setShowReply(false)} onDone={(newPost) => { setShowReply(false); if (onReply) onReply(newPost); }} />}
      {!readonly && showEdit && <EditModal post={post} onClose={() => setShowEdit(false)} onDone={(updated) => { setShowEdit(false); if (onUpdate) onUpdate(updated); }} />}
      {!readonly && showReport && <ReportModal post={post} onClose={() => setShowReport(false)} />}
      {viewerIndex >= 0 && (post.media_attachments?.length ?? 0) > 0 && (
        <MediaViewer
          media={post.media_attachments || []}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(-1)}
        />
      )}
      {!readonly && showRewrite && (
        <RewriteModal post={post} initialContent={rewriteContent ?? undefined} initialSummary={rewriteSummary} initialVisibility={post.visibility} initialMedia={rewriteMedia} onClose={closeRewrite} onDone={() => { if (onUpdate) onUpdate(); }} />
      )}
    </>
  );
});
export default PostCard;
