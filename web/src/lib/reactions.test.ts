import { describe, expect, it } from "vitest";
import { domainFromHandle, emojiKeyword, parseReactionKey } from "./reactions";

describe("reaction badge keys", () => {
  it("splits domain-separated custom emoji badges", () => {
    expect(parseReactionKey(":ablobcat_frustration:@kitsunesoba.com")).toEqual({
      reaction: ":ablobcat_frustration:",
      domain: "kitsunesoba.com",
    });
    expect(emojiKeyword(":ablobcat_frustration:")).toBe("ablobcat_frustration");
  });

  it("keeps local and unicode reactions unchanged", () => {
    expect(parseReactionKey(":wave:")).toEqual({ reaction: ":wave:", domain: "" });
    expect(parseReactionKey("★")).toEqual({ reaction: "★", domain: "" });
  });

  it("extracts domains only from remote handles", () => {
    expect(domainFromHandle("villain@kitsunesoba.com")).toBe("kitsunesoba.com");
    expect(domainFromHandle("alice")).toBe("");
    expect(domainFromHandle(undefined)).toBe("");
  });
});
