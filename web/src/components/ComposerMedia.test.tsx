import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import ComposerMedia from "@/components/ComposerMedia";

type MediaItem = { id: number; url: string; type: string; file?: File; alt?: string; preview?: string };

function Harness({ items, setItems }: { items: MediaItem[]; setItems: React.Dispatch<React.SetStateAction<MediaItem[]>> }) {
  const [altIdx, setAltIdx] = useState<number | null>(null);
  return <ComposerMedia items={items} setItems={setItems} altIdx={altIdx} setAltIdx={setAltIdx} revokePreviews={vi.fn()} />;
}

describe("ComposerMedia", () => {
  it("renders image and video thumbnails", () => {
    render(<Harness
      items={[{ id: 1, url: "https://cdn/a.jpg", type: "image" }, { id: 2, url: "https://cdn/b.mp4", type: "video" }]}
      setItems={vi.fn()}
    />);
    expect(document.querySelector('img[src="https://cdn/a.jpg"]')).toBeInTheDocument();
    expect(document.querySelector('video[src="https://cdn/b.mp4"]')).toBeInTheDocument();
  });

  it("removes an item and calls revokePreviews", async () => {
    const user = userEvent.setup();
    const setItems = vi.fn();
    const revoke = vi.fn();
    const items = [{ id: 1, url: "https://cdn/a.jpg", type: "image", preview: "blob:1" }, { id: 2, url: "https://cdn/b.jpg", type: "image", preview: "blob:2" }];
    render(<ComposerMedia items={items} setItems={setItems} altIdx={null} setAltIdx={vi.fn()} revokePreviews={revoke} />);
    const removeButtons = Array.from(document.querySelectorAll("span")).filter(s => s.textContent === "×");
    expect(removeButtons.length).toBeGreaterThanOrEqual(1);
    await user.click(removeButtons[0]);
    expect(revoke).toHaveBeenCalledWith([items[0]]);
    expect(setItems).toHaveBeenCalledWith([items[1]]);
  });

  it("opens the alt modal and accepts text input", async () => {
    const user = userEvent.setup();
    const setItems = vi.fn();
    render(<Harness items={[{ id: 1, url: "https://cdn/a.jpg", type: "image" }]} setItems={setItems} />);
    const altBtn = screen.getByTitle("미디어 설명");
    await user.click(altBtn);
    expect(screen.getByText("미디어 설명")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/푸른 하늘/)).toBeInTheDocument();
    const confirmBtn = screen.getByText("확인");
    await user.click(confirmBtn);
    expect(screen.queryByText("시각 장애인을 위한")).not.toBeInTheDocument();
  });
});
