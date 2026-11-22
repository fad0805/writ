import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import MediaGallery from "@/components/MediaGallery";

describe("MediaGallery", () => {
  it("lazy-loads images and defers video metadata", () => {
    const { container } = render(
      <MediaGallery
        media={[
          { url: "/uploads/a.png", type: "image", alt: "first" },
          { url: "/uploads/b.mp4", type: "video" },
        ]}
        sensitive={false}
        revealed={false}
        onReveal={vi.fn()}
        onHide={vi.fn()}
        onOpen={vi.fn()}
      />,
    );

    expect(container.querySelector('img[alt="first"]')).toHaveAttribute("loading", "lazy");
    expect(container.querySelector("video")).toHaveAttribute("preload", "none");
  });
});
