import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ComposerLinkPreview from "@/components/ComposerLinkPreview";
import type { PostData } from "@/lib/api";

function makePost(): PostData {
  return {
    id: 7,
    number: "12",
    ap_id: "https://example.test/posts/7",
    url: "https://example.test/@alice/7",
    content: "<p>hello</p>",
    summary: "",
    visibility: "public",
    created_at: "2026-01-01T00:00:00Z",
    author: { id: 1, username: "alice", display_name: "앨리스", avatar: "", is_remote: false, remote_url: "" } as PostData["author"],
    likes_count: 0,
    boosts_count: 0,
    replies_count: 0,
    liked: false,
    boosted: false,
    bookmarked: false,
    is_mine: false,
    reply_context: null,
  } as PostData;
}

describe("ComposerLinkPreview", () => {
  it("shows loading state when a quote URL is set but post not fetched yet", () => {
    render(<ComposerLinkPreview quotePost={null} quoteUrl="https://example.test/@a/1" linkPreview={null} linkPreviewLoading={false} onClearQuote={vi.fn()} onClearPreview={vi.fn()} />);
    expect(screen.getByText("게시글 불러오는 중...")).toBeInTheDocument();
  });

  it("renders the quoted post card", () => {
    render(<ComposerLinkPreview quotePost={makePost()} quoteUrl="https://example.test/@a/7" linkPreview={null} linkPreviewLoading={false} onClearQuote={vi.fn()} onClearPreview={vi.fn()} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("renders the link preview with title, description and hostname", () => {
    render(<ComposerLinkPreview
      quotePost={null}
      quoteUrl=""
      linkPreview={{ url: "https://news.example.com/x", title: "뉴스 제목", description: "요약 문장", image: "" }}
      linkPreviewLoading={false}
      onClearQuote={vi.fn()}
      onClearPreview={vi.fn()}
    />);
    expect(screen.getByText("뉴스 제목")).toBeInTheDocument();
    expect(screen.getByText("요약 문장")).toBeInTheDocument();
    expect(screen.getByText("news.example.com")).toBeInTheDocument();
  });

  it("hides the link preview while a quote is present", () => {
    render(<ComposerLinkPreview
      quotePost={null}
      quoteUrl="https://example.test/@a/1"
      linkPreview={{ url: "https://news.example.com/x", title: "T", description: "D", image: "" }}
      linkPreviewLoading={false}
      onClearQuote={vi.fn()}
      onClearPreview={vi.fn()}
    />);
    expect(screen.queryByText("T")).not.toBeInTheDocument();
  });

  it("shows link preview loading indicator", () => {
    render(<ComposerLinkPreview quotePost={null} quoteUrl="" linkPreview={null} linkPreviewLoading={true} onClearQuote={vi.fn()} onClearPreview={vi.fn()} />);
    expect(screen.getByText("링크 미리보기 불러오는 중...")).toBeInTheDocument();
  });

  it("clears the quote and preview via the × buttons", async () => {
    const user = userEvent.setup();
    const onClearQuote = vi.fn();
    const onClearPreview = vi.fn();
    const { rerender } = render(<ComposerLinkPreview quotePost={null} quoteUrl="https://x.test/1" linkPreview={null} linkPreviewLoading={false} onClearQuote={onClearQuote} onClearPreview={onClearPreview} />);
    const quoteX = Array.from(document.querySelectorAll("button")).find(b => b.textContent === "×");
    await user.click(quoteX!);
    expect(onClearQuote).toHaveBeenCalled();

    rerender(<ComposerLinkPreview quotePost={null} quoteUrl="" linkPreview={{ url: "https://n.test/y", title: "T", description: "", image: "" }} linkPreviewLoading={false} onClearQuote={onClearQuote} onClearPreview={onClearPreview} />);
    const previewX = Array.from(document.querySelectorAll("button")).find(b => b.textContent === "×");
    await user.click(previewX!);
    expect(onClearPreview).toHaveBeenCalled();
  });
});
