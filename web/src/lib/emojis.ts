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
        const fresh: CustomEmoji[] = await res.json();
        if (cache === null) {
          cache = fresh;
        } else {
          const cur = cache as CustomEmoji[];
          for (const e of fresh) {
            if (!cur.some((c) => c.keyword === e.keyword)) {
              cur.push(e);
            }
          }
        }
        return cache || [];
      }
    } catch {}
    cache = [];
    return [];
  })();
  return fetchPromise;
}

export function invalidateEmojiCache() {
  cache = null;
  fetchPromise = null;
}

export function renderCustomEmojis(html: string, emojis: CustomEmoji[]): string {
  if (!emojis || emojis.length === 0) return html;
  // Deduplicate by keyword — first seen wins
  const seen = new Set<string>();
  const uniq = emojis.filter(e => { if (seen.has(e.keyword)) return false; seen.add(e.keyword); return true; });
  const sorted = [...uniq].sort((a, b) => b.keyword.length - a.keyword.length);
  for (const emoji of sorted) {
    if (!emoji.url) continue;
    const kw = emoji.keyword;
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`:${escaped}:`, "g");
    html = html.replace(re, `<img src="${emoji.url}" alt=":${kw}:" title=":${kw}:" class="custom-emoji" width="33" height="33" style="width:33px;height:33px;vertical-align:middle;display:inline-block;object-fit:contain">`);
  }
  return html;
}
