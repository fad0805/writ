import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { PostData } from "@/lib/api";
import MiniPostCard from "@/components/MiniPostCard";

vi.mock("@/lib/emojis", () => ({
  useEmojiList: () => [],
  injectEmojis: vi.fn(),
  renderCustomEmojis: (value: string) => value,
  renderCustomEmojisWithOverrides: (value: string) => value,
}));

function makePost(overrides: Partial<PostData> = {}): PostData {
  return {
    id: 1,
    content: "<p>본문</p>",
    summary: "",
    author: { id: 1, username: "user" },
    media_attachments: [{ url: "https://cdn/a.jpg", type: "image" }],
    ...overrides,
  } as unknown as PostData;
}

describe("MiniPostCard", () => {
  it("hides media when the post has a content warning", () => {
    render(<MiniPostCard post={makePost({ summary: "스포일러" })} />);
    expect(document.querySelector('img[src="https://cdn/a.jpg"]')).not.toBeInTheDocument();
  });

  it("shows media when the post has no content warning", () => {
    render(<MiniPostCard post={makePost()} />);
    expect(document.querySelector('img[src="https://cdn/a.jpg"]')).toBeInTheDocument();
  });
});
