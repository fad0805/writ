"use client";

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

export function injectEmojis(list: CustomEmojiRaw[]) {
  if (!cache) cache = [];
  let changed = false;
  if (!(window as any).__emojiMap) {
    (window as any).__emojiMap = {};
  }
  const emojiMap = (window as any).__emojiMap;

  for (const e of list) {
    if (!e.keyword) continue;
    // 기존 캐시에 있는지 확인
    const existing = cache.find((c) => c.keyword === e.keyword);
    if (!existing) {
      cache.push({ ...e, category: "remote" });
      changed = true;
    } else if (e.url && existing.url !== e.url) {
      // URL이 변경되었거나 업데이트된 경우 갱신
      existing.url = e.url;
      changed = true;
    }

    // map도 항상 최신으로 갱신
    if (e.url && emojiMap[e.keyword] !== e.url) {
      emojiMap[e.keyword] = e.url;
      changed = true;
    }
  }

  if (changed && typeof window !== "undefined") {
    cache = [...cache];
    (window as any).__emojiCache = cache;
    // 💡 핵심: 조각난 list가 아니라 전체 최신 cache를 이벤트와 구독자에 전달!
    window.dispatchEvent(new CustomEvent("emojichange", { detail: cache }));
    _emojiSubscribers.forEach(fn => fn(cache as CustomEmoji[]));
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
    try {
      const res = await fetch(`/api/emojis?limit=9999&offset=0`, { credentials: "include" });
      if (!res.ok) { cache = []; fetchPromise = null; return cache as CustomEmoji[]; }
      const data = await res.json();
      cache = data.emojis || [];
    } catch { cache = []; }
    if (typeof window !== "undefined") (window as any).__emojiCache = cache;
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
      // ★ 이 부분이 핵심입니다. 로딩이 끝났을 때 모든 구독자에게 새 데이터를 쏴줍니다.
      _emojiSubscribers.forEach(fn => fn(freshList));
    });
  }
  return () => { _emojiSubscribers.delete(cb); };
}

export function renderCustomEmojis(html: string, emojis: CustomEmoji[], size?: number): string {
  if (!emojis || emojis.length === 0) return html;
  const sz = size ?? 33;
  const seen = new Set<string>();
  const uniq = emojis.filter(e => { if (seen.has(e.keyword)) return false; seen.add(e.keyword); return true; });
  const sorted = [...uniq].sort((a, b) => b.keyword.length - a.keyword.length);
  for (const emoji of sorted) {
    if (!emoji.url) continue;
    const safeUrl = emoji.url.replace(/"/g, "%22").replace(/</g, "%3C").replace(/>/g, "%3E");
    if (!safeUrl.startsWith("https:")) continue;
    const kw = emoji.keyword;
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`:${escaped}:`, "g");
    html = html.replace(re, `<img src="${safeUrl}" alt=":${kw}:" title=":${kw}:" class="custom-emoji" width="${sz}" height="${sz}" style="width:${sz}px;height:${sz}px;vertical-align:middle;display:inline-block;object-fit:contain">`);
  }
  return html;
}
