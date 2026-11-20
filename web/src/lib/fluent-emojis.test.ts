import { describe, expect, it } from "vitest";
import { loadFluentEmojis } from "@/lib/fluent-emojis";

describe("fluent emojis", () => {
  it("loads the full list with automatic search aliases", async () => {
    const groups = await loadFluentEmojis();
    expect(groups.length).toBeGreaterThan(5);
    const all = groups.flatMap((group) => group.emojis);
    expect(all.length).toBeGreaterThan(1000);

    const grinning = all.find((emoji) => emoji.slug === "grinning-face");
    expect(grinning?.char).toBe("😀");
    expect(grinning?.aliases).toContain("grinning_face");
    expect(grinning?.aliases).toContain("grinning face");

    const tone = all.find((emoji) => emoji.slug === "thumbs-up-medium-light");
    expect(tone?.char).toBe("👍🏼");
    expect(tone?.aliases).toContain("thumbs-up-medium-light");

    // Fluent에 국가기가 없어도 전체 Unicode 국기는 목록에 포함된다.
    const flag = all.find((emoji) => emoji.char === "🇦🇫");
    expect(flag).toBeTruthy();
    expect(flag?.slug).toBeUndefined();
    expect(all.filter((emoji) => emoji.group === "깃발").length).toBeGreaterThan(250);
  });
});
