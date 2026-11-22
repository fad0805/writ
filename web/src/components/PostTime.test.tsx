import { describe, expect, it } from "vitest";
import { formatPostTime } from "@/components/PostTime";

const NOW = new Date("2026-11-22T12:00:00Z").getTime();

describe("formatPostTime", () => {
  it("shows seconds, minutes, and hours only while crossing each threshold", () => {
    expect(formatPostTime(new Date(NOW - 5_000).toISOString(), NOW)).toBe("5초 전");
    expect(formatPostTime(new Date(NOW - 5 * 60_000).toISOString(), NOW)).toBe("5분 전");
    expect(formatPostTime(new Date(NOW - 5 * 3_600_000).toISOString(), NOW)).toBe("5시간 전");
  });

  it("falls back to an absolute timestamp after a day", () => {
    const old = new Date(NOW - 25 * 3_600_000).toISOString();
    expect(formatPostTime(old, NOW)).not.toContain("시간 전");
  });

  it("ignores missing or invalid timestamps", () => {
    expect(formatPostTime(null, NOW)).toBe("");
    expect(formatPostTime("not-a-date", NOW)).toBe("");
  });
});
