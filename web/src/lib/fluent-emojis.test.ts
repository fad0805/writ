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
  });
});
