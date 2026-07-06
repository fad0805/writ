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

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  if (cache !== null) return cache;
  if (fetchPromise) return fetchPromise;
  fetchPromise = (async () => {
    try {
      const res = await fetch("/api/emojis", { credentials: "include" });
      if (res.ok) {
        cache = await res.json();
        return cache || [];
      }
    } catch {}
    cache = [];
    return [];
  })();
  return fetchPromise;
}

export function invalidateEmojiCache() {
  cache = [];
  fetchPromise = null;
}

export function renderCustomEmojis(html: string, emojis: CustomEmoji[]): string {
  if (!emojis || emojis.length === 0) return html;
  const sorted = [...emojis].sort((a, b) => b.keyword.length - a.keyword.length);
  for (const emoji of sorted) {
    const allKeywords = [emoji.keyword, ...(emoji.aliases || [])];

    for (const kw of allKeywords) {
      const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const re = new RegExp(`:${escaped}:`, "g");
      html = html.replace(re, `<img src="${emoji.url}" alt=":${kw}:" title=":${kw}:" class="custom-emoji" width="33" height="33" style="width:33px;height:33px;vertical-align:middle;display:inline-block;object-fit:contain">`);
    }
  }
  return html;
}
