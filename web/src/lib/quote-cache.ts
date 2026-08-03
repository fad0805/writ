import { PostData } from "@/lib/api";

const STORAGE_KEY = "writ:quote-cache";
const MAX_STORED = 100;

const memoryCache = new Map<string, PostData>();
const pending = new Map<string, Promise<PostData | null>>();

function isValidQuote(d: unknown): d is PostData {
  if (!d || typeof d !== "object") return false;
  const obj = d as Record<string, unknown>;
  return obj.id != null && !!obj.author;
}

function loadSessionCache(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    for (const [k, v] of Object.entries(parsed)) {
      if (isValidQuote(v) && !memoryCache.has(k)) memoryCache.set(k, v);
    }
  } catch {}
}

function persist(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    const entries = Array.from(memoryCache.entries()).slice(-MAX_STORED);
    const obj: Record<string, unknown> = {};
    for (const [k, v] of entries) obj[k] = v;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {}
}

export function getCachedQuote(key: string): PostData | null {
  return memoryCache.get(key) || null;
}

export function setQuoteCache(key: string, post: PostData): void {
  if (!isValidQuote(post)) return;
  memoryCache.set(key, post);
  persist();
}

export function clearQuoteCache(): void {
  memoryCache.clear();
  pending.clear();
  if (typeof sessionStorage !== "undefined") {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch {}
  }
}

export function getQuote(key: string, fetcher: () => Promise<PostData | null>): Promise<PostData | null> {
  const cached = memoryCache.get(key);
  if (cached) return Promise.resolve(cached);
  const inFlight = pending.get(key);
  if (inFlight) return inFlight;
  const p = fetcher()
    .then((d) => {
      pending.delete(key);
      if (d && isValidQuote(d)) {
        setQuoteCache(key, d);
        return d;
      }
      return null;
    })
    .catch(() => {
      pending.delete(key);
      return null;
    });
  pending.set(key, p);
  return p;
}

loadSessionCache();
