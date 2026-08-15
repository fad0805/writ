import { describe, expect, it } from "vitest";
import { renderCustomEmojis, renderReaction } from "@/lib/emojis";
import type { CustomEmoji } from "@/lib/emojis";

const emojis: CustomEmoji[] = [
  { keyword: "heart", file_name: "heart.png", url: "https://cdn.example/heart.png", aliases: [] },
  { keyword: "blob_happy", file_name: "blob_happy.png", url: "/local/blob_happy.png", aliases: [] },
];

describe("renderCustomEmojis", () => {
  it("replaces :keyword: with an img tag", () => {
    const out = renderCustomEmojis("i :heart: you", emojis);
    expect(out).toContain('<img src="https://cdn.example/heart.png"');
    expect(out).toContain('alt=":heart:"');
    expect(out).toContain('class="custom-emoji"');
  });

  it("is case-insensitive for keywords", () => {
    const out = renderCustomEmojis("i :HEART: you", emojis);
    expect(out).toContain('src="https://cdn.example/heart.png"');
  });

  it("leaves unknown shortcodes untouched", () => {
    expect(renderCustomEmojis("i :unknown: you", emojis)).toBe("i :unknown: you");
  });

  it("returns input unchanged for empty emoji list", () => {
    expect(renderCustomEmojis("x :heart: y", [])).toBe("x :heart: y");
  });

  it("prefers the longest keyword match", () => {
    const out = renderCustomEmojis(":blob_happy:", emojis);
    expect(out).toContain("/local/blob_happy.png");
  });

  it("honors the size argument", () => {
    const out = renderCustomEmojis(":heart:", emojis, 16);
    expect(out).toContain('width="16" height="16"');
  });

  it("escapes unsafe URL characters", () => {
    const evil = { keyword: "evil", file_name: "evil.jpg", url: 'https://cdn.example/a".jpg', aliases: [] } as CustomEmoji;
    const out = renderCustomEmojis(":evil:", [evil]);
    expect(out).not.toContain('src="https://cdn.example/a".jpg"');
  });
});

describe("renderReaction", () => {
  it("escapes HTML in the reaction text", () => {
    expect(renderReaction("<script>", emojis)).not.toContain("<script>");
    expect(renderReaction("<script>", emojis)).toContain("&lt;script&gt;");
  });
});
