import { describe, expect, it } from "vitest";
import { formatRelative, rewriteLinks } from "@/lib/postContent";

describe("formatRelative", () => {
  const now = 1_000_000_000_000;
  const sec = 1000;
  const min = 60 * sec;
  const hour = 60 * min;
  const day = 24 * hour;

  it("formats sub-minute as seconds", () => {
    expect(formatRelative(String(new Date(now - 5 * sec)), now)).toBe("5초");
  });

  it("formats minutes and seconds", () => {
    expect(formatRelative(String(new Date(now - (2 * min + 10 * sec))), now)).toBe("2분 10초");
  });

  it("formats hours", () => {
    expect(formatRelative(String(new Date(now - 3 * hour)), now)).toBe("3시간");
  });

  it("formats days", () => {
    expect(formatRelative(String(new Date(now - 2 * day)), now)).toBe("2일");
  });

  it("handles future timestamps with absolute value", () => {
    expect(formatRelative(String(new Date(now + 4 * sec)), now)).toBe("4초");
  });
});

describe("rewriteLinks", () => {
  it("wraps hashtags in anchor links", () => {
    const out = rewriteLinks("hello #writ");
    expect(out).toContain('<a href="/explore?q=%23writ" class="hashtag-link">#writ</a>');
  });

  it("wraps bare URLs with https links", () => {
    const out = rewriteLinks("see https://example.com/x");
    expect(out).toContain('<a href="https://example.com/x"');
    expect(out).toContain('target="_blank" rel="noopener noreferrer"');
  });

  it("does not double-wrap already-anchored links", () => {
    const out = rewriteLinks('check <a href="https://example.com">link</a>');
    expect(out).toContain('<a href="https://example.com">link</a>');
    expect(out).not.toContain('href="/explore?q=%23');
  });

  it("protects plain tags from linkification", () => {
    const out = rewriteLinks("<plain>not #a hashtag and https://no.link/x</plain>");
    expect(out).toContain("<plain>not #a hashtag and https://no.link/x</plain>");
  });

  it("truncates long display URLs", () => {
    const long = `https://example.com/${"a".repeat(60)}`;
    const out = rewriteLinks(`x ${long}`);
    expect(out).toContain('href="https://example.com/');
    expect(out).not.toContain(`>${long}</a>`);
  });
});
