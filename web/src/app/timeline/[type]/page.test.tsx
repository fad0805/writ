import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import type { PostData } from "@/lib/api";
import { api } from "@/lib/api";
import TimelinePage from "@/app/timeline/[type]/page";
import { MAX_TL_POSTS } from "@/lib/timeline";

const h = vi.hoisted(() => {
  const renders: number[] = [];
  return { renders };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ type: "home" }),
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

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    accountSnapshot: () => 1,
    api: {
      ...actual.api,
      timeline: vi.fn(),
      getPost: vi.fn(),
      like: vi.fn(),
      unlike: vi.fn(),
      bookmark: vi.fn(),
      unbookmark: vi.fn(),
      boost: vi.fn(),
      unboost: vi.fn(),
    },
  };
});

vi.mock("@/components/PostCard", async () => {
  const React = await import("react");
  const MockPostCard = ({ post }: { post: { id: number } }) => {
    h.renders.push(post.id);
    return React.createElement("div", { "data-testid": "pc" }, String(post.id));
  };
  return { default: React.memo(MockPostCard) };
});

vi.mock("@/components/PostForm", () => ({ default: () => null }));
vi.mock("@/components/ReplyModal", () => ({ default: () => null }));
vi.mock("@/components/Icon", () => ({ default: () => null }));

vi.mock("@/components/InfiniteScroll", async () => {
  const React = await import("react");
  return {
    default: ({ children }: { children: ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  };
});

class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  close() {}
}

vi.stubGlobal("EventSource", MockEventSource);

function makePost(id: number, content = `content-${id}`): PostData {
  return {
    id,
    number: String(id),
    ap_id: `ap:${id}`,
    url: `https://example.test/@me/${id}`,
    content,
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
    is_deleted: false,
  };
}

function pushSse(data: unknown) {
  const es = MockEventSource.instances[0];
  if (!es) throw new Error("no EventSource created");
  act(() => {
    es.onmessage?.({ data: JSON.stringify(data) });
  });
}

beforeEach(() => {
  MockEventSource.instances = [];
  h.renders.length = 0;
  sessionStorage.clear();
  localStorage.clear();
  vi.mocked(api.timeline).mockReset();
});

describe("TimelinePage", () => {
  it("renders the loaded feed", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1), makePost(2), makePost(3)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    const cards = await screen.findAllByTestId("pc");
    expect(cards).toHaveLength(3);
    expect(h.renders).toEqual([1, 2, 3]);
  });

  it("does not re-render unrelated cards when a single post updates via SSE", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1), makePost(2), makePost(3)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    await screen.findAllByTestId("pc");

    pushSse({ ...makePost(2, "updated title"), type: "update" });

    const count = (id: number) => h.renders.filter((x) => x === id).length;
    expect(count(2)).toBe(2);
    expect(count(1)).toBe(1);
    expect(count(3)).toBe(1);
  });

  it("caps the feed at MAX_TL_POSTS when many new posts stream in", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1), makePost(2), makePost(3)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    await screen.findAllByTestId("pc");

    const total = MAX_TL_POSTS + 50;
    for (let id = 4; id <= total + 3; id++) {
      pushSse(makePost(id));
    }

    const cards = screen.getAllByTestId("pc");
    expect(cards).toHaveLength(MAX_TL_POSTS);
    expect(cards[0]).toHaveTextContent(String(total + 3));
  });
});