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
  for (const e of list) {
    if (!cache.some((c) => c.keyword === e.keyword)) {
      cache.push({ ...e, category: "remote" });
    }
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
    const all: CustomEmoji[] = [];
    let offset = 0;
    const limit = 30;
    try {
      while (true) {
        const res = await fetch(`/api/emojis?limit=${limit}&offset=${offset}`, { credentials: "include" });
        if (!res.ok) break;
        const data = await res.json();
        const batch: CustomEmoji[] = data.emojis || data || [];
        for (const e of batch) {
          if (!all.some((c) => c.keyword === e.keyword)) {
            all.push(e);
          }
        }
        if (!data.has_more) break;
        offset += limit;
      }
    } catch {}
    cache = all;
    fetchPromise = null;
    cacheTs = storedTs || Date.now();
    return cache;
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
    const img = `<img src="${safeUrl}" alt=":${emoji.keyword}:" title=":${emoji.keyword}:" class="custom-emoji" width="${sz}" height="${sz}" style="width:${sz}px;height:${sz}px;vertical-align:middle;display:inline-block;object-fit:contain">`;
    const kw = emoji.keyword;
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(`:${escaped}:`, "g"), img);
    for (const a of (emoji.aliases || [])) {
      const aesc = a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      html = html.replace(new RegExp(`:${aesc}:`, "g"), img);
    }
  }
  return html;
}
