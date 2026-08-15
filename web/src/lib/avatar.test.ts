import { describe, expect, it } from "vitest";
import { avatarColor, hashColor } from "@/lib/avatar";

describe("avatarColor", () => {
  it("returns a valid hsl color", () => {
    const c = avatarColor("alice");
    expect(c).toMatch(/^hsl\((\d+), 35%, 40%\)$/);
  });

  it("is deterministic for the same username", () => {
    expect(avatarColor("alice")).toBe(avatarColor("alice"));
  });

  it("keeps hue in the [0, 360) range", () => {
    for (const name of ["a", "b", "zzz", "가나다", "user@example.com", "WRIT"]) {
      const match = avatarColor(name).match(/^hsl\((\d+), 35%, 40%\)$/);
      expect(match).toBeTruthy();
      const hue = Number(match?.[1]);
      expect(hue).toBeGreaterThanOrEqual(0);
      expect(hue).toBeLessThan(360);
    }
  });

  it("handles empty string", () => {
    expect(() => avatarColor("")).not.toThrow();
  });
});

describe("hashColor", () => {
  it("honors saturation and lightness arguments", () => {
    const c = hashColor("x", 60, 30);
    expect(c).toBe(`hsl(${hashColor("x", 60, 30).match(/hsl\((\d+)/)?.[1]}, 60%, 30%)`);
  });

  it("defaults to 35% saturation and 45% lightness", () => {
    const c = hashColor("x");
    expect(c).toMatch(/^hsl\((\d+), 35%, 45%\)$/);
  });

  it("is deterministic", () => {
    expect(hashColor("writ")).toBe(hashColor("writ"));
  });
});
