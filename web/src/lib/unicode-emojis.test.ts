import { describe, expect, it } from "vitest";
import { loadUnicodeEmojis } from "@/lib/unicode-emojis";

describe("unicode emojis", () => {
  it("loads every Unicode emoji with automatic search aliases", async () => {
    const groups = await loadUnicodeEmojis();
    expect(groups.length).toBeGreaterThan(5);
    const all = groups.flatMap((group) => group.emojis);
    expect(all.length).toBeGreaterThan(1900);

    const grinning = all.find((emoji) => emoji.char === "😀");
    expect(grinning?.aliases).toContain("grinning_face");
    expect(grinning?.aliases).toContain("grinning face");

    const tone = all.find((emoji) => emoji.char === "👍🏼");
    expect(tone?.aliases).toContain("thumbs_up_medium_light");

    // Fluent에 없던 국가기도 전체 목록에 포함된다.
    expect(all.find((emoji) => emoji.char === "🇦🇫")).toBeTruthy();
    expect(all.filter((emoji) => emoji.group === "깃발").length).toBeGreaterThan(250);
  });
});
