"use client";
import { useState, useEffect } from "react";

export interface CustomEmojiRaw {
  keyword: string;
  file_name: string;
  url: string;
  aliases: string[];
}

export interface CustomEmoji {
  id?: number;
  keyword: string;
  file_name: string;
  category?: string;
  aliases?: string[];
  url: string;
}

declare global {
  interface Window {
    __emojiCache?: CustomEmoji[];
    __emojiMap?: Record<string, string | undefined>;
  }
}

export function injectEmojis(list: CustomEmojiRaw[]) {
  if (!cache) cache = window.__emojiCache ? [...window.__emojiCache] : [];
  let changed = false;
  if (!window.__emojiMap) {
    window.__emojiMap = {};
  }
  const emojiMap = window.__emojiMap;

  for (const e of list) {
    if (!e.keyword) continue;
    // 기존 캐시에 있는지 확인
    const existing = cache.find((c) => c.keyword === e.keyword);
    if (!existing) {
      cache.push({ ...e, category: "remote" });
      changed = true;
    }
    // 같은 키워드가 이미 전역 캐시에 있으면 이 글의 도메인 이모지로 덮어쓰지 않는다.
    // (다른 서버 글의 렌더링을 오염시키지 않도록. 글별 이모지는 PostCard가
    //  _emojis를 우선 병합해 해결한다.)

    // map도 항상 최신으로 갱신
    if (e.url && emojiMap[e.keyword] !== e.url && emojiMap[e.keyword] === undefined) {
      emojiMap[e.keyword] = e.url;
      changed = true;
    }
  }

  if (changed && typeof window !== "undefined") {
    cache = [...cache];
    window.__emojiCache = cache;
    window.dispatchEvent(new CustomEvent("emojichange", { detail: cache }));
    _emojiSubscribers.forEach(fn => fn(cache as CustomEmoji[]));
    _versionListeners.forEach(fn => fn());
  }
}

let cache: CustomEmoji[] | null = null;
let fetchPromise: Promise<CustomEmoji[]> | null = null;
let cacheTs = 0;

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  if (typeof localStorage !== "undefined") {
    const storedTs = parseInt(localStorage.getItem("emoji_cache_ts") || "0", 10);
    const stored = localStorage.getItem("emoji_cache");
    if (storedTs > cacheTs && stored) {
      try {
        const parsed: CustomEmoji[] = JSON.parse(stored);
        cache = parsed;
        cacheTs = storedTs;
        return parsed;
      } catch {}
    }
  }
  if (cache !== null) return cache;
  if (fetchPromise) return fetchPromise;
  fetchPromise = (async () => {
    let server: CustomEmoji[] = [];
    try {
      const res = await fetch(`/api/emojis?limit=9999&offset=0`, { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        server = data.emojis || [];
      }
    } catch {}
    // 서버 목록으로 덮어쓰면 injectEmojis로 주입된 원격 이모지가 사라져
    // 표시 이름 이모지가 렌더링됐다 풀렸다 하는 문제가 생김. 원격 이모지를 보존한다.
    const prev = window.__emojiCache;
    cache = server;
    if (Array.isArray(prev) && prev.length) {
      const known = new Set(cache.map(e => e.keyword));
      for (const e of prev) {
        if (e && e.keyword && e.url && !known.has(e.keyword)) {
          cache.push({ ...e, category: e.category || "remote" });
        }
      }
    }
    if (typeof window !== "undefined") window.__emojiCache = cache;
    fetchPromise = null;
    cacheTs = Date.now();
    if (typeof localStorage !== "undefined") {
      try { localStorage.setItem("emoji_cache", JSON.stringify(cache)); localStorage.setItem("emoji_cache_ts", String(cacheTs)); } catch {}
    }
    return cache as CustomEmoji[];
  })();
  return fetchPromise;
}

export function invalidateEmojiCache() {
  cache = null;
  fetchPromise = null;
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem("emoji_cache");
    localStorage.setItem("emoji_cache_ts", Date.now().toString());
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("emojichange"));
  }
  getCustomEmojis().then(list => {
    _emojiSubscribers.forEach(fn => fn(list));
    _versionListeners.forEach(fn => fn());
  });
}

const _emojiSubscribers: Set<(emojis: CustomEmoji[]) => void> = new Set();

export function subscribeEmojis(cb: (emojis: CustomEmoji[]) => void): () => void {
  // 이미 캐시가 있으면 마운트 직후 바로 전달
  if (cache) { 
    cb(cache); 
  }
  _emojiSubscribers.add(cb);
  // 캐시가 아직 없다면 비동기로 가져온 뒤, 모든 구독자에게 전파!
  if (!cache) {
    getCustomEmojis().then(list => {
      const freshList = [...list];
      _emojiSubscribers.forEach(fn => fn(freshList));
      _versionListeners.forEach(fn => fn());
    });
  }
  return () => { _emojiSubscribers.delete(cb); };
}

const _versionListeners = new Set<() => void>();

export function useEmojiList(): CustomEmoji[] {
  const [emojis, setEmojis] = useState<CustomEmoji[]>(() =>
    typeof window !== "undefined" && window.__emojiCache
      ? window.__emojiCache
      : (cache || [])
  );

  useEffect(() => {
    const handler = () => setEmojis(window.__emojiCache || cache || []);
    _versionListeners.add(handler);

    getCustomEmojis().then(list => {
      setEmojis(list);
    });

    return () => { _versionListeners.delete(handler); };
  }, []);

  return emojis;
}

export function renderReaction(reaction: string, emojis: CustomEmoji[], size?: number): string {
  const escaped = reaction.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return renderCustomEmojis(escaped, emojis, size);
}

const renderCache = new WeakMap<CustomEmoji[], { re: RegExp | null; emojiByKeyword: Map<string, CustomEmoji> }>();

function getRenderData(emojis: CustomEmoji[]) {
  let data = renderCache.get(emojis);
  if (!data) {
    const seen = new Set<string>();
    const uniq: CustomEmoji[] = [];
    for (const e of emojis) {
      if (!e || !e.keyword || !e.url) continue;
      const lowerKw = e.keyword.toLowerCase();
      if (seen.has(lowerKw)) continue;
      seen.add(lowerKw);
      const safeUrl = e.url.replace(/"/g, "%22").replace(/</g, "%3C").replace(/>/g, "%3E");
      if (!safeUrl.startsWith("https:") && !safeUrl.startsWith("/")) continue;
      uniq.push({ ...e, url: safeUrl });
    }
    uniq.sort((a, b) => b.keyword.length - a.keyword.length);
    const parts: string[] = [];
    const emojiByKeyword = new Map<string, CustomEmoji>();
    for (const e of uniq) {
      parts.push(e.keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      emojiByKeyword.set(e.keyword.toLowerCase(), e);
    }
    data = { re: parts.length > 0 ? new RegExp(`:(${parts.join("|")}):`, "gi") : null, emojiByKeyword };
    renderCache.set(emojis, data);
  }
  return data;
}

export function renderCustomEmojis(html: string, emojis: CustomEmoji[], size?: number): string {
  if (!html || !emojis || emojis.length === 0) return html;
  const sz = size ?? 33;
  const { re, emojiByKeyword } = getRenderData(emojis);
  if (!re) return html;
  return html.replace(re, (match, kw: string) => {
    const emoji = emojiByKeyword.get(kw.toLowerCase());
    if (!emoji) return match;
    const kwAttr = emoji.keyword.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<img src="${emoji.url}" alt=":${kwAttr}:" title=":${kwAttr}:" class="custom-emoji" width="${sz}" height="${sz}" style="width:${sz}px;height:${sz}px;vertical-align:middle;display:inline-block;object-fit:contain">`;
  });
}
