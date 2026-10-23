import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { PostData } from "@/lib/api";
import { api } from "@/lib/api";
import { clearQuoteCache } from "@/lib/quote-cache";
import PostCard from "@/components/PostCard";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

vi.mock("next/link", async () => {
  const React = await import("react");
  return {
    default: ({ children, href }: { children: ReactNode; href: string }) =>
      React.createElement("a", { href }, children),
  };
});

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { id: 1 }, loading: false, refresh: vi.fn() }),
}));

vi.mock("@/lib/emojis", () => ({
  useEmojiList: () => [],
  injectEmojis: vi.fn(),
  renderCustomEmojis: (value: string) => value,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getPost: vi.fn(),
    },
  };
});

function makePost(overrides: Partial<PostData> = {}): PostData {
  return {
    id: 1,
    number: "n1",
    ap_id: "ap:1",
    content: "<p>quoting post</p>",
    summary: "",
    visibility: "public",
    created_at: "2026-01-01T00:00:00Z",
    author: {
      id: 1,
      username: "me",
      display_name: "Me",
      avatar: "",
      summary: "",
      is_admin: false,
      is_remote: false,
    },
    likes_count: 0,
    boosts_count: 0,
    replies_count: 0,
    liked: false,
    boosted: false,
    bookmarked: false,
    is_mine: false,
    reply_context: null,
    ...overrides,
  };
}

describe("PostCard quote loading", () => {
  beforeEach(() => {
    vi.mocked(api.getPost).mockReset();
    clearQuoteCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("shows the blocked/muted placeholder immediately for a hidden quote", () => {
    render(
      <PostCard
        post={makePost({
          quote_of_id: 99,
          quote_hidden: true,
          quote_hidden_url: "/post/99",
        })}
      />,
    );

    expect(screen.getByText("차단/뮤트한 사용자의 글")).toBeInTheDocument();
    expect(screen.queryByText("인용 불러오는 중...")).toBeNull();
    expect(api.getPost).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not retry a failed quote fetch forever", async () => {
    vi.mocked(api.getPost).mockRejectedValue(new Error("blocked"));

    render(<PostCard post={makePost({ quote_of_id: 99 })} />);

    await waitFor(() => expect(api.getPost).toHaveBeenCalledTimes(1));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(api.getPost).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("인용 불러오는 중...")).toBeNull();
  });
});
