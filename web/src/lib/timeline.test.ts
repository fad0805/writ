import { describe, expect, it } from "vitest";
import { capPosts, pruneDeletedIds, MAX_TL_POSTS, MAX_DELETED_IDS } from "@/lib/timeline";

describe("capPosts", () => {
  it("keeps the array as-is when under the cap", () => {
    const arr = [1, 2, 3];
    expect(capPosts(arr, 5)).toBe(arr);
  });

  it("trims the oldest (tail) posts beyond the cap", () => {
    const arr = [1, 2, 3, 4, 5];
    expect(capPosts(arr, 3)).toEqual([1, 2, 3]);
  });

  it("applies the default cap when max is omitted", () => {
    const arr = Array.from({ length: MAX_TL_POSTS + 50 }, (_, i) => i);
    expect(capPosts(arr)).toHaveLength(MAX_TL_POSTS);
  });
});

describe("pruneDeletedIds", () => {
  it("keeps the set as-is when under the cap", () => {
    const set = new Set([1, 2, 3]);
    expect(pruneDeletedIds(set, 10)).toBe(set);
    expect(set.size).toBe(3);
  });

  it("removes the oldest ids first when over the cap", () => {
    const set = new Set([1, 2, 3, 4, 5]);
    pruneDeletedIds(set, 3);
    expect(set.has(1)).toBe(false);
    expect(set.has(2)).toBe(false);
    expect(new Set([3, 4, 5])).toEqual(set);
  });

  it("applies the default cap when max is omitted", () => {
    const set = new Set(Array.from({ length: MAX_DELETED_IDS + 50 }, (_, i) => i));
    expect(pruneDeletedIds(set).size).toBe(MAX_DELETED_IDS);
  });

  it("is idempotent on a set that is already within bounds", () => {
    const set = new Set([1, 2]);
    expect(pruneDeletedIds(pruneDeletedIds(set, 2), 2)).toBe(set);
  });
});