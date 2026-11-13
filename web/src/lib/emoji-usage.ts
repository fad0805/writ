import { storageGet, storageSet } from "@/lib/storage";

const KEY = "writ:emoji-usage";

export function recordEmojiUsage(emoji: string) {
  if (!emoji || emoji === "★") return;
  try {
    const raw = storageGet(KEY);
    const counts: Record<string, number> = raw ? JSON.parse(raw) : {};
    counts[emoji] = (counts[emoji] || 0) + 1;
    storageSet(KEY, JSON.stringify(counts));
  } catch {}
}

export function getFrequentEmojis(limit = 14): string[] {
  try {
    const raw = storageGet(KEY);
    if (!raw) return [];
    const counts: Record<string, number> = JSON.parse(raw);
    return Object.entries(counts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, limit)
      .map(([emoji]) => emoji);
  } catch {
    return [];
  }
}
