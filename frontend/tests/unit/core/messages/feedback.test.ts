import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import {
  getFeedbackByRunId,
  getMessageFeedback,
} from "@/core/messages/feedback";
import { getMessageGroups } from "@/core/messages/utils";

function message(
  id: string,
  type: Message["type"],
  content: string,
  runId?: string,
  feedback?: { rating: number; comment: string | null } | null,
): Message {
  return {
    id,
    type,
    content,
    ...(runId ? { run_id: runId } : {}),
    ...(feedback !== undefined ? { feedback } : {}),
  } as Message;
}

function toolCall(id: string, runId: string, callId: string): Message {
  return {
    ...message(id, "ai", "", runId),
    tool_calls: [{ id: callId, name: "write_file", args: {} }],
  } as Message;
}

function toolResult(id: string, runId: string, callId: string): Message {
  return {
    ...message(id, "tool", "ok", runId),
    tool_call_id: callId,
  } as Message;
}

describe("getMessageFeedback", () => {
  test("returns null when the message carries no feedback field", () => {
    expect(getMessageFeedback(message("ai-1", "ai", "Hi"))).toBeNull();
  });

  test("returns null for the backend's explicit no-feedback marker", () => {
    expect(
      getMessageFeedback(message("ai-1", "ai", "Hi", "run-1", null)),
    ).toBeNull();
  });

  test("returns the attached feedback object", () => {
    const feedback = { rating: 1, comment: "great" };
    expect(
      getMessageFeedback(message("ai-1", "ai", "Hi", "run-1", feedback)),
    ).toBe(feedback);
  });
});

describe("getFeedbackByRunId", () => {
  test("collects one entry per run, latest non-null feedback wins", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "First task"),
      message("ai-1", "ai", "First answer", "run-1", {
        rating: 1,
        comment: null,
      }),
      message("ai-1b", "ai", "Superseded bubble", "run-1", {
        rating: -1,
        comment: "revised",
      }),
      message("human-2", "human", "Second task"),
      message("ai-2", "ai", "Second answer", "run-2", null),
    ]);

    const byRunId = getFeedbackByRunId(groups);
    expect(byRunId.get("run-1")).toEqual({ rating: -1, comment: "revised" });
    expect(byRunId.has("run-2")).toBe(false);
  });

  test("finds feedback attached to a non-assistant group", () => {
    // The backend anchors feedback on the run's last AI message, which can be
    // a tool-calling message that groups into a processing group. The UI
    // resolves by run_id, so that feedback must still be discoverable.
    const groups = getMessageGroups([
      message("human-1", "human", "Run a tool"),
      toolCall("ai-tool-1", "run-1", "call-1"),
      toolResult("tool-1", "run-1", "call-1"),
      message("ai-last", "ai", "Done", "run-1"),
    ]);
    // Attach the feedback to the tool-call message, as the backend would.
    (groups[1]?.messages[0] as Message & { feedback?: unknown }).feedback = {
      rating: -1,
      comment: "tool path wrong",
    };

    expect(getFeedbackByRunId(groups).get("run-1")).toEqual({
      rating: -1,
      comment: "tool path wrong",
    });
  });

  test("ignores messages without a run id", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "Hello"),
      message("ai-1", "ai", "Hi", undefined, { rating: 1, comment: null }),
    ]);

    expect(getFeedbackByRunId(groups).size).toBe(0);
  });
});
