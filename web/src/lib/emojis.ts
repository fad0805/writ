"use client";

export interface CustomEmoji {
  id: number;
  keyword: string;
  file_name: string;
  category: string;
  aliases: string[];
  url: string;
}

let cache: CustomEmoji[] = [];
let fetchPromise: Promise<CustomEmoji[]> | null = null;

export async function getCustomEmojis(): Promise<CustomEmoji[]> {
  if (cache) return cache;
  if (fetchPromise) return fetchPromise;
  fetchPromise = (async () => {
    try {
      const res = await fetch("/api/emojis", { credentials: "include" });
      if (res.ok) {
        cache = await res.json();
        return cache;
      }
    } catch {}
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
