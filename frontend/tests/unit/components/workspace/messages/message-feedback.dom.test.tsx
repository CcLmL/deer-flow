import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

rs.mock("@/core/api/feedback", () => ({
  upsertFeedback: rs.fn(
    async (
      _threadId: string,
      _runId: string,
      rating: number,
      comment?: string,
    ) => ({
      feedback_id: "fb-1",
      rating,
      comment: comment ?? null,
    }),
  ),
  deleteFeedback: rs.fn(async () => undefined),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: enUS }),
}));

import { MessageFeedback } from "@/components/workspace/messages/message-feedback";
import { deleteFeedback, upsertFeedback } from "@/core/api/feedback";
import { enUS } from "@/core/i18n/locales/en-US";

const mockedUpsert = rs.mocked(upsertFeedback);
const mockedDelete = rs.mocked(deleteFeedback);

function commentText(content: string) {
  return (_text: string, element: Element | null) =>
    element?.tagName === "P" && element.textContent === content;
}

function renderFeedback(
  initialFeedback: { rating: number; comment: string | null } | null = null,
) {
  return render(
    <MessageFeedback
      threadId="thread-1"
      runId="run-1"
      initialFeedback={
        initialFeedback ? { feedback_id: "fb-0", ...initialFeedback } : null
      }
    />,
  );
}

beforeEach(() => {
  mockedUpsert.mockClear();
  mockedDelete.mockClear();
});

afterEach(cleanup);

describe("MessageFeedback (DOM)", () => {
  it("renders the thumb buttons and no comment before any feedback exists", () => {
    renderFeedback();

    expect(screen.getByRole("button", { name: "Helpful" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Not helpful" })).toBeDefined();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stores the category marker and comment through the feedback dialog", async () => {
    renderFeedback();

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Share feedback");

    fireEvent.click(screen.getByText("Incorrect or incomplete"));
    fireEvent.change(screen.getByRole("textbox", { name: "Share details" }), {
      target: { value: "It says 31°C but it is 25°C." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockedUpsert).toHaveBeenCalledWith(
        "thread-1",
        "run-1",
        -1,
        "~Incorrect or incomplete~\nIt says 31°C but it is 25°C.",
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    // The displayed comment shows the category label without the marker.
    expect(
      screen.getByText(
        commentText("Incorrect or incomplete\nIt says 31°C but it is 25°C."),
      ),
    ).toBeDefined();
  });

  it("clicking the active thumb deletes the feedback and its comment", async () => {
    renderFeedback({
      rating: -1,
      comment: "Incorrect or incomplete\nToo slow.",
    });
    expect(
      screen.getByText(commentText("Incorrect or incomplete\nToo slow.")),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));

    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledWith("thread-1", "run-1");
    });
    expect(
      screen.queryByText(commentText("Incorrect or incomplete\nToo slow.")),
    ).toBeNull();
  });

  it("re-selects the saved category and pre-fills only the comment details", async () => {
    renderFeedback({
      rating: -1,
      comment: "~Slow or has issues~\nTook 40 seconds.",
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    await screen.findByRole("dialog");

    expect(
      screen
        .getByRole("button", { name: "Slow or has issues" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    const textbox = screen.getByRole("textbox", { name: "Share details" });
    expect((textbox as HTMLTextAreaElement).value).toBe("Took 40 seconds.");
    // The displayed comment shows the label and details without the marker.
    expect(
      screen.getByText(commentText("Slow or has issues\nTook 40 seconds.")),
    ).toBeDefined();
  });

  it("re-selects a bare-label legacy category with empty details", async () => {
    renderFeedback({ rating: 1, comment: "Style or tone" });

    fireEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    await screen.findByRole("dialog");

    expect(
      screen
        .getByRole("button", { name: "Style or tone" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    const textbox = screen.getByRole("textbox", { name: "Share details" });
    expect((textbox as HTMLTextAreaElement).value).toBe("");
  });

  it("treats legacy plain comments as details only", async () => {
    renderFeedback({ rating: 1, comment: "Old comment" });

    fireEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    await screen.findByRole("dialog");

    const textbox = screen.getByRole("textbox", { name: "Share details" });
    expect((textbox as HTMLTextAreaElement).value).toBe("Old comment");
  });

  it("cancelling the dialog keeps the existing feedback unchanged", async () => {
    renderFeedback({ rating: 1, comment: "Style or tone" });

    fireEvent.click(screen.getByRole("button", { name: "Edit comment" }));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(mockedUpsert).not.toHaveBeenCalled();
    expect(screen.getByText("Style or tone")).toBeDefined();
  });

  it("switching the rating through the dialog replaces the saved feedback", async () => {
    renderFeedback({ rating: 1, comment: "Old comment" });

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    await screen.findByRole("dialog");

    // The saved details are prefilled so editing does not silently drop them.
    const textbox = screen.getByRole("textbox", { name: "Share details" });
    expect((textbox as HTMLTextAreaElement).value).toBe("Old comment");
    fireEvent.change(textbox, { target: { value: "New comment" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockedUpsert).toHaveBeenCalledWith(
        "thread-1",
        "run-1",
        -1,
        "New comment",
      );
    });
  });
});
