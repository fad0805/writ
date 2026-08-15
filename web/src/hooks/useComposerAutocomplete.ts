import { useCallback, useEffect, useRef, useState } from "react";
import { api, User, PostData } from "@/lib/api";
import { getCustomEmojis, CustomEmoji } from "@/lib/emojis";
import { useInlineAutocomplete, useSeriesSearch } from "@/hooks/useAutocomplete";

const MENTION_PREV_CHAR = /\s/;
const MENTION_WORD_END = /@[a-zA-Z_][a-zA-Z0-9_]*(?:@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})?/g;
const EMOJI_PREV_CHAR = /[\s:]/;
const EMOJI_WORD_END = /[\s:]/;
const HASHTAG_PREV_CHAR = /\s/;
const HASHTAG_WORD_END = /[\s#]/;

export function useComposerAutocomplete(params: {
  content: string;
  setContent: React.Dispatch<React.SetStateAction<string>>;
  taRef: React.MutableRefObject<HTMLTextAreaElement | null>;
  shareUrl?: string;
}) {
  const { content, setContent, taRef, shareUrl } = params;

  const searchMentions = useCallback(async (q: string) => (await api.autocomplete(q)).users, []);
  const searchEmojis = useCallback(async (q: string) => {
    const all = await getCustomEmojis();
    const lq = q.toLowerCase();
    return all.filter(e => e.category !== "remote" && (e.keyword.startsWith(lq) || (e.aliases || []).some(a => a.startsWith(lq))));
  }, []);
  const searchHashtags = useCallback(async (q: string) => {
    const res = await fetch(`/api/search/tags?q=${encodeURIComponent(q)}`, { credentials: "include" });
    if (res.ok) {
      const d = await res.json();
      return d.tags?.map((t: { name: string }) => t.name) || [];
    }
    return [];
  }, []);

  const {
    query: emojiQuery,
    results: emojiResults,
    idx: emojiIdx,
    pos: emojiPos,
    setIdx: setEmojiIdx,
    setResults: setEmojiResults,
    detect: detectEmoji,
    insert: emojiInsert,
    onKeyDown: emojiOnKeyDown,
  } = useInlineAutocomplete<CustomEmoji>({
    trigger: ":",
    prevCharRegex: EMOJI_PREV_CHAR,
    wordEndRegex: EMOJI_WORD_END,
    search: searchEmojis,
    content,
    setContent,
    taRef,
  });

  const {
    results: mentionUsers,
    idx: mentionIdx,
    pos: mentionPos,
    setIdx: setMentionIdx,
    detect: detectMention,
    insert: mentionInsert,
    onKeyDown: mentionOnKeyDown,
  } = useInlineAutocomplete<User>({
    trigger: "@",
    prevCharRegex: MENTION_PREV_CHAR,
    wordEndRegex: MENTION_WORD_END,
    search: searchMentions,
    content,
    setContent,
    taRef,
  });

  const {
    results: hashtagResults,
    idx: hashtagIdx,
    pos: hashtagPos,
    setIdx: setHashtagIdx,
    detect: detectHashtag,
    insert: hashtagInsert,
    onKeyDown: hashtagOnKeyDown,
  } = useInlineAutocomplete<string>({
    trigger: "#",
    prevCharRegex: HASHTAG_PREV_CHAR,
    wordEndRegex: HASHTAG_WORD_END,
    search: searchHashtags,
    content,
    setContent,
    taRef,
  });

  const {
    show: showSeriesSearch,
    query: seriesSearchQ,
    results: seriesResults,
    idx: seriesIdx,
    pos: seriesPos,
    setQuery: setSeriesSearchQ,
    setIdx: setSeriesIdx,
    inputRef: seriesSearchRef,
    detect: detectSeries,
    insert: insertSeries,
    handleKeyDown: seriesOnKeyDown,
  } = useSeriesSearch({ content, setContent, taRef });

  const [linkPreview, setLinkPreview] = useState<{ url: string; title: string; description: string; image: string } | null>(null);
  const [linkPreviewLoading, setLinkPreviewLoading] = useState(false);
  const linkPreviewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastUrlRef = useRef<string | null>(null);
  const quoteTiedToContentRef = useRef(false);
  const [quoteUrl, setQuoteUrl] = useState(shareUrl || "");
  const [quotePost, setQuotePost] = useState<PostData | null>(null);

  useEffect(() => {
    if (shareUrl && !quotePost) {
      const base = typeof window !== "undefined" ? window.location.origin : "";
      const escapedBase = base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      // 1. 기존 유저 포스트 패턴: /@유저아이디/숫자
      const localMatch = base ? shareUrl.match(new RegExp(`^${escapedBase}/@([^/]+)/(\\d+)`)) : null;
      // 2. 새 시리즈/에피소드 패턴: /series/숫자/episodes/숫자
      const seriesEpisodeMatch = base ? shareUrl.match(new RegExp(`^${escapedBase}/series/(\\d+)/episodes/(\\d+)`)) : null;
      // 3. 새 시리즈 by-number 패턴: /series/by-number/문자열/문자열
      const seriesByNumberMatch = base ? shareUrl.match(new RegExp(`^${escapedBase}/series/by-number/([^/]+)/([^/]+)`)) : null;


      (async () => {
        let fetchUrl = "";
        let isPostRequest = false;
        const form = new FormData();
        form.append("url", shareUrl);

        if (localMatch) {
          // 1. 기존 유저 포스트 GET 요청
          fetchUrl = `/api/${localMatch[1]}/${localMatch[2]}`;
        } else if (seriesEpisodeMatch) {
          // 2. 시리즈 에피소드용 (만약 POST로 url을 넘기는 구조라면)
          fetchUrl = "/api/fetch-episode";
          isPostRequest = true;
        } else if (seriesByNumberMatch) {
          // 3. 시리즈 관련 POST 요청
          fetchUrl = "/api/fetch-series";
          isPostRequest = true;
        } else {
          // 4. 그 외 외부 페치 fallback
          fetchUrl = "/api/fetch-post";
          isPostRequest = true;
        }

        try {
          const options: RequestInit = { credentials: "include" };
          if (isPostRequest) {
            options.method = "POST";
            options.body = form;
          }

          const r = await fetch(fetchUrl, options);
          if (r.ok) {
            const data = await r.json();
            setQuotePost(data);
            return;
          }
        } catch (e) {
          console.error("데이터 페치 실패:", e);
        }
      })();
    }
  }, [shareUrl, quotePost]);

  useEffect(() => {
    const urlRegex = /https?:\/\/[^\s<>"')\]]+/i;
    const match = content.match(urlRegex);
    const url = match ? match[0].replace(/[.,;:!?)]+$/, "") : null;
    if (lastUrlRef.current !== url) {
      lastUrlRef.current = url;
      if (linkPreviewTimerRef.current) clearTimeout(linkPreviewTimerRef.current);
      setLinkPreview(null);
      if (url) {
        if (quoteUrl === url) return;
        if (linkPreview && linkPreview.url === url && !quoteUrl) return;
        quoteTiedToContentRef.current = true;
        linkPreviewTimerRef.current = setTimeout(async () => {
          setLinkPreviewLoading(true);

          const base = typeof window !== "undefined" ? window.location.origin : "";
          const escapedBase = base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          const localMatch = base ? url.match(new RegExp(`^${escapedBase}/@([^/]+)/(\\d+)`)) : null;

          let quoteResolved = false;

          if (localMatch) {
            setQuoteUrl(url);
            try {
              const r = await fetch(`/api/by-number/${localMatch[1]}/${localMatch[2]}`, { credentials: "include" });
              if (r.ok) { setQuotePost(await r.json()); quoteResolved = true; }
            } catch {}
          }

          if (!quoteResolved) {
            const form = new FormData(); form.append("url", url);
            try {
              const r = await fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form });
              if (r.ok) {
                const d = await r.json();
                if (d._emojis) { import("@/lib/emojis").then(m => m.injectEmojis(d._emojis)); }
                setQuoteUrl(url); setQuotePost(d); quoteResolved = true;
              }
            } catch {}
          }

          if (!quoteResolved) {
            setQuoteUrl(url);
            setQuotePost(null);
            try {
              const data = await api.fetchLinkPreview(url);
              if (data && data.title) setLinkPreview(data);
            } catch {}
          } else {
            setLinkPreview(null);
          }

          setLinkPreviewLoading(false);
        }, 300);
        return () => { if (linkPreviewTimerRef.current) clearTimeout(linkPreviewTimerRef.current); };
      }
      if (quoteTiedToContentRef.current) {
        quoteTiedToContentRef.current = false;
        setQuoteUrl("");
        setQuotePost(null);
      }
    }
  }, [content, quoteUrl, linkPreview]);

  // Close emoji picker on scroll/resize/click-outside/Escape
  useEffect(() => {
    if (!emojiQuery) return;
    const close = () => setEmojiResults([]);
    const keyHandler = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    document.addEventListener("keydown", keyHandler);
    const clickHandler = (e: MouseEvent) => {
      const popup = document.querySelector('.emoji-autocomplete');
      if (popup && !popup.contains(e.target as Node)) close();
    };
    setTimeout(() => document.addEventListener("click", clickHandler), 0);
    return () => {
      document.removeEventListener("keydown", keyHandler);
      document.removeEventListener("click", clickHandler);
    };
  }, [emojiQuery, setEmojiResults]);

  const insertEmoji = (emo: CustomEmoji) => emojiInsert(emo.keyword, ": ");

  const insertMention = (u: User) => {
    let handle = u.username;
    if (u.is_remote && u.remote_url) {
      try {
        const h = new URL(u.remote_url).hostname;
        if (h) handle = `${u.username}@${h}`;
      } catch {}
    }
    mentionInsert(handle);
  };

  const insertHashtag = (tag: string) => hashtagInsert(tag);

  return {
    emoji: { query: emojiQuery, results: emojiResults, idx: emojiIdx, pos: emojiPos, setIdx: setEmojiIdx, setResults: setEmojiResults, onKeyDown: emojiOnKeyDown, insert: emojiInsert, detect: detectEmoji },
    mention: { results: mentionUsers, idx: mentionIdx, pos: mentionPos, setIdx: setMentionIdx, onKeyDown: mentionOnKeyDown, insert: mentionInsert, detect: detectMention },
    hashtag: { results: hashtagResults, idx: hashtagIdx, pos: hashtagPos, setIdx: setHashtagIdx, onKeyDown: hashtagOnKeyDown, insert: hashtagInsert, detect: detectHashtag },
    series: { show: showSeriesSearch, query: seriesSearchQ, results: seriesResults, idx: seriesIdx, pos: seriesPos, setQuery: setSeriesSearchQ, setIdx: setSeriesIdx, inputRef: seriesSearchRef, detect: detectSeries, insert: insertSeries, onKeyDown: seriesOnKeyDown },
    linkPreview,
    setLinkPreview,
    linkPreviewLoading,
    quoteUrl,
    setQuoteUrl,
    quotePost,
    setQuotePost,
    insertEmoji,
    insertMention,
    insertHashtag,
  };
}
