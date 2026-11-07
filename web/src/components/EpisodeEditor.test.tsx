import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import EpisodeEditor from "@/components/EpisodeEditor";

function Harness({ initial, next }: { initial: string; next: string }) {
  const [value, setValue] = useState(initial);
  const [syncKey, setSyncKey] = useState(0);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setValue(next);
          setSyncKey((k) => k + 1);
        }}
      >
        불러오기
      </button>
      <EpisodeEditor value={value} onChange={setValue} syncKey={syncKey} />
    </>
  );
}

describe("EpisodeEditor", () => {
  it("syncs externally replaced content when syncKey changes", async () => {
    const user = userEvent.setup();
    render(<Harness initial="<p>에피소드 본문</p>" next="<p>임시저장 본문</p>" />);

    expect(screen.getByText("에피소드 본문")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "불러오기" }));

    await waitFor(() => {
      expect(screen.getByText("임시저장 본문")).toBeInTheDocument();
    });
    expect(screen.queryByText("에피소드 본문")).not.toBeInTheDocument();
  });
});
