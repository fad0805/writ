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
  for (const e of list) {
    if (!cache.some((c) => c.keyword === e.keyword)) {
      cache.push({ ...e, category: "remote" });
      changed = true;
    }
  }
  if (changed && typeof window !== "undefined") {
    if ((window as any).__emojiMap) {
      for (const e of list) {
        if (e.keyword && e.url && !(window as any).__emojiMap[e.keyword]) {
          (window as any).__emojiMap[e.keyword] = e.url;
        }
      }
    }
    window.dispatchEvent(new CustomEvent("emojichange", { detail: list }));
  }
}

let cache: CustomEmoji[] | null = null;
let fetchPromise: Promise<CustomEmoji[]> | null = null;
let cacheTs = 0;

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  let storedTs = 0;
  if (typeof localStorage !== "undefined") {
    storedTs = parseInt(localStorage.getItem("emoji_cache_ts") || "0", 10);
    if (storedTs > cacheTs) {
      cache = null;
      fetchPromise = null;
      cacheTs = storedTs;
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
    fetchPromise = null;
    cacheTs = storedTs || Date.now();
    return cache as CustomEmoji[];
  })();
  return fetchPromise;
}

export function invalidateEmojiCache() {
  cache = null;
  fetchPromise = null;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem("emoji_cache_ts", Date.now().toString());
  }
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
