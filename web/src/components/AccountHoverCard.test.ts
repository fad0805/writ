import { describe, expect, it } from "vitest";
import { accountUsernameFromHref } from "@/components/AccountHoverCard";

describe("accountUsernameFromHref", () => {
  it("extracts local account links", () => {
    expect(accountUsernameFromHref("/@alice")).toBe("alice");
    expect(accountUsernameFromHref("/@alice@example.com")).toBe("alice@example.com");
    expect(accountUsernameFromHref("/profile/bob")).toBe("bob");
  });

  it("ignores post links and external URLs", () => {
    expect(accountUsernameFromHref("/@alice/123")).toBeNull();
    expect(accountUsernameFromHref("/@alice?tab=media")).toBe("alice");
    expect(accountUsernameFromHref("https://other.example/@alice")).toBeNull();
    expect(accountUsernameFromHref("/explore?q=%23tag")).toBeNull();
  });
});
