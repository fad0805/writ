import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import ComposerPoll from "@/components/ComposerPoll";

function Harness({ options, setOptions }: { options: string[]; setOptions: React.Dispatch<React.SetStateAction<string[]>> }) {
  const lastRef = useRef<HTMLInputElement | null>(null);
  return (
    <ComposerPoll
      options={options}
      setOptions={setOptions}
      expiresIn={1440}
      setExpiresIn={vi.fn()}
      lastRef={lastRef}
    />
  );
}

function StatefulHarness() {
  const [options, setOptions] = useState<string[]>(["", ""]);
  const lastRef = useRef<HTMLInputElement | null>(null);
  return <ComposerPoll options={options} setOptions={setOptions} expiresIn={1440} setExpiresIn={vi.fn()} lastRef={lastRef} />;
}

describe("ComposerPoll", () => {
  it("renders the poll title and option inputs", () => {
    render(<Harness options={["a", "b"]} setOptions={vi.fn()} />);
    expect(screen.getByText("투표")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("선택지 1")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("선택지 2")).toBeInTheDocument();
  });

  it("adds an empty option when typing in the last field", async () => {
    const user = userEvent.setup();
    render(<StatefulHarness />);
    const last = screen.getByPlaceholderText("선택지 2");
    await user.type(last, "c");
    expect(screen.getByPlaceholderText("선택지 3")).toBeInTheDocument();
  });

  it("renders the remove button only when more than two options exist", () => {
    render(<Harness options={["a", "b"]} setOptions={vi.fn()} />);
    expect(screen.queryAllByRole("button", { name: "×" })).toHaveLength(0);
  });

  it("removes an option via the × button when present", async () => {
    const user = userEvent.setup();
    const setOptions = vi.fn();
    render(<Harness options={["a", "b", "c"]} setOptions={setOptions} />);
    const removeButtons = screen.getAllByRole("button", { name: "×" });
    expect(removeButtons).toHaveLength(3);
    await user.click(removeButtons[0]);
    expect(setOptions).toHaveBeenCalledWith(["b", "c"]);
  });

  it("shows the duration options and current selection", () => {
    render(<Harness options={["a", "b"]} setOptions={vi.fn()} />);
    expect(screen.getByRole("option", { name: "24시간" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "7일" })).toBeInTheDocument();
  });
});
