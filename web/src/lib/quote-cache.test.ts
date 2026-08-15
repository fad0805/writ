import { beforeEach, describe, expect, it } from "vitest";
import {
  clearQuoteCache,
  getCachedQuote,
  getQuote,
  setQuoteCache,
} from "@/lib/quote-cache";
import type { PostData } from "@/lib/api";

function makePost(id: number): PostData {
  return {
    id,
    author: { id: 1, username: "a", display_name: "A" },
  } as unknown as PostData;
}

beforeEach(() => {
  sessionStorage.clear();
  clearQuoteCache();
});

describe("quote-cache", () => {
  it("stores and retrieves valid posts", () => {
    setQuoteCache("k", makePost(7));
    expect(getCachedQuote("k")?.id).toBe(7);
  });

  it("rejects invalid payloads", () => {
    setQuoteCache("bad", {} as PostData);
    expect(getCachedQuote("bad")).toBeNull();
  });

  it("deduplicates concurrent fetches for the same key", async () => {
    let calls = 0;
    const fetcher = () => {
      calls += 1;
      return Promise.resolve(makePost(3));
    };
    const [a, b] = await Promise.all([getQuote("k", fetcher), getQuote("k", fetcher)]);
    expect(calls).toBe(1);
    expect(a?.id).toBe(3);
    expect(b?.id).toBe(3);
  });

  it("returns the cached value on subsequent calls", async () => {
    const fetcher = () => Promise.resolve(makePost(5));
    await getQuote("k", fetcher);
    let calls = 0;
    const result = await getQuote("k", () => {
      calls += 1;
      return Promise.resolve(makePost(9));
    });
    expect(calls).toBe(0);
    expect(result?.id).toBe(5);
  });

  it("swallows fetcher errors and returns null", async () => {
    const result = await getQuote("k", () => Promise.reject(new Error("network")));
    expect(result).toBeNull();
  });

  it("clears the cache", () => {
    setQuoteCache("k", makePost(1));
    clearQuoteCache();
    expect(getCachedQuote("k")).toBeNull();
  });
});
