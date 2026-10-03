import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { PostData } from "@/lib/api";
import { api } from "@/lib/api";
import TimelinePage from "@/app/timeline/[type]/page";
import { MAX_TL_POSTS } from "@/lib/timeline";

const h = vi.hoisted(() => {
  const renders: number[] = [];
  const avatars: { id: number; authorId: number; avatar: string }[] = [];
  return { renders, avatars };
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
  const MockPostCard = ({ post }: { post: { id: number; author?: { id: number; avatar: string } } }) => {
    h.renders.push(post.id);
    h.avatars.push({ id: post.id, authorId: post.author?.id ?? 0, avatar: post.author?.avatar ?? "" });
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
  private listeners = new Map<string, Set<(ev?: unknown) => void>>();
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (ev?: unknown) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(cb);
  }
  removeEventListener(type: string, cb: (ev?: unknown) => void) {
    this.listeners.get(type)?.delete(cb);
  }
  fire(type: string) {
    for (const cb of this.listeners.get(type) || []) cb();
  }
  close() {}
}

vi.stubGlobal("EventSource", MockEventSource);

function makePost(id: number, content = `content-${id}`, authorId = 1): PostData {
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
      id: authorId,
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

function timelineEs(): MockEventSource {
  const es = MockEventSource.instances.find((i) => i.url.startsWith("/api/timeline/stream"));
  if (!es) throw new Error("no timeline EventSource created");
  return es;
}

function pushSse(data: unknown) {
  act(() => {
    timelineEs().onmessage?.({ data: JSON.stringify(data) });
  });
}

// 상세→뒤로가기를 흉내낸다: 타임라인을 떠났다가 5분 이내로 다시 마운트될 때
// 쓰이는 sessionStorage 캐시를 심는다. accountSnapshot()는 1로 mock되어 있다.
function seedTimelineCache(entries: Record<string, { posts: PostData[]; hasMore?: boolean; cursor?: string | null }>) {
  const now = Date.now();
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entries)) {
    out[k] = { posts: v.posts, hasMore: v.hasMore ?? false, cursor: v.cursor ?? null, ts: now };
  }
  sessionStorage.setItem("writ:tl-cache:v3:1", JSON.stringify(out));
}

beforeEach(() => {
  MockEventSource.instances = [];
  h.renders.length = 0;
  h.avatars.length = 0;
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

  it("swaps in the new author avatar when a remote profile_update arrives", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1, "c1", 7), makePost(2, "c2", 8)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    await screen.findAllByTestId("pc");

    pushSse({ type: "profile_update", user_id: 7, avatar: "/uploads/avatars/remote/new.png" });

    // 방금 렌더된 값으로 판정한다 (같은 post가 다시 렌더될 수 있음)
    const latest = new Map<number, { authorId: number; avatar: string }>();
    for (const a of h.avatars) latest.set(a.id, { authorId: a.authorId, avatar: a.avatar });
    expect(latest.get(1)).toEqual({ authorId: 7, avatar: "/uploads/avatars/remote/new.png" });
    // 다른 작성자는 그대로여야 한다
    expect(latest.get(2)).toEqual({ authorId: 8, avatar: "" });
    // 글이 새로 추가되지는 않는다
    expect(screen.getAllByTestId("pc")).toHaveLength(2);
  });

  it("never treats an event without a post id as a new post", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1), makePost(2)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    await screen.findAllByTestId("pc");

    // 글 id가 없는 이벤트는 전부 무시되어야 한다 (가짜 글이 렌더 크래시를 낸다)
    pushSse({ type: "profile_update", user_id: 7 });
    pushSse({ event: "notif", unread: 3 });
    pushSse({ type: "something_new" });

    expect(screen.getAllByTestId("pc")).toHaveLength(2);
    expect(screen.queryByText("undefined")).toBeNull();
  });

  it("revalidates a cached timeline in the background so back-navigation is not stale", async () => {
    // 캐시에는 글 1만 있다. 상세 페이지에 있는 동안 글 2, 3이 도착했다.
    seedTimelineCache({ home: { posts: [makePost(1)] } });
    vi.mocked(api.timeline).mockResolvedValue({
      posts: [makePost(3), makePost(2), makePost(1)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });

    render(<TimelinePage />);
    // 캐시가 먼저 그려진다 (빠른 첫 페인트, 스피너 없음)
    expect((await screen.findAllByTestId("pc")).map((c) => c.textContent)).toEqual(["1"]);

    // 곧바로 재검증되어 놓친 글이 앞에 보충된다
    await waitFor(() => expect(screen.getAllByTestId("pc")).toHaveLength(3));
    expect(screen.getAllByTestId("pc").map((c) => c.textContent)).toEqual(["3", "2", "1"]);
  });

  it("keeps showing the cached timeline when background revalidation fails", async () => {
    seedTimelineCache({ home: { posts: [makePost(1), makePost(2)] } });
    vi.mocked(api.timeline).mockRejectedValue(new Error("offline"));

    render(<TimelinePage />);
    expect((await screen.findAllByTestId("pc")).map((c) => c.textContent)).toEqual(["1", "2"]);

    await act(async () => {
      await Promise.resolve();
    });
    // 실패해도 이미 그린 캐시가 빈 화면으로 덮이지 않는다
    expect(screen.getAllByTestId("pc").map((c) => c.textContent)).toEqual(["1", "2"]);
  });

  it("does not drop posts that arrived over SSE while revalidating", async () => {
    seedTimelineCache({ home: { posts: [makePost(1)] } });
    type TimelineResponse = Awaited<ReturnType<typeof api.timeline>>;
    let release: (v: TimelineResponse) => void = () => {};
    vi.mocked(api.timeline).mockReturnValue(
      new Promise<TimelineResponse>((res) => {
        release = res;
      }),
    );

    render(<TimelinePage />);
    expect((await screen.findAllByTestId("pc")).map((c) => c.textContent)).toEqual(["1"]);

    // 재검증이 떠 있는 동안 SSE로 글 2가 들어온다
    act(() => {
      pushSse(makePost(2, "sse-arrival"));
    });
    expect(screen.getAllByTestId("pc").map((c) => c.textContent)).toEqual(["2", "1"]);

    // 이제 재검증이 끝난다. 서버 첫 페이지에 글 1만 있어도 SSE로 온 글 2는 살아 있어야 한다
    await act(async () => {
      release({ posts: [makePost(1)], has_more: false, cursor: null, timeline_type: "home" });
    });
    expect(screen.getAllByTestId("pc").map((c) => c.textContent)).toEqual(["2", "1"]);
  });

  it("shows a disconnect banner while SSE is down and hides it on reconnect", async () => {
    vi.mocked(api.timeline).mockResolvedValueOnce({
      posts: [makePost(1), makePost(2)],
      has_more: false,
      cursor: null,
      timeline_type: "home",
    });
    render(<TimelinePage />);
    await screen.findAllByTestId("pc");

    expect(screen.queryByRole("status")).toBeNull();

    act(() => {
      timelineEs().fire("error");
    });

    const banner = screen.getByRole("status");
    expect(banner.textContent).toContain("실시간");
    expect(banner.textContent).toContain("연결이 끊겼어요");

    act(() => {
      timelineEs().fire("open");
    });

    expect(screen.queryByRole("status")).toBeNull();
  });
});