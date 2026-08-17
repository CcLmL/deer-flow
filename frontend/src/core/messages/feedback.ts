import type { Message } from "@langchain/langgraph-sdk";

import type { FeedbackData } from "@/core/api/feedback";

import { getMessageRunId } from "./run-duration";
import type { MessageGroup } from "./utils";

/**
 * The backend attaches run-scoped feedback to the last AI message of each run
 * and null to every other row, so history messages carry the field while
 * live-streamed messages do not.
 */
export type MessageWithFeedback = Message & {
  feedback?: FeedbackData | null;
};

/** Read the feedback attached to a message; absent or null yields null. */
export function getMessageFeedback(message: Message): FeedbackData | null {
  return (message as MessageWithFeedback).feedback ?? null;
}

/**
 * Collect the latest non-null feedback per run across every group type.
 *
 * The backend anchors feedback on each run's last *AI message*, which can sit
 * in a processing/present-files/subagent group when the run ends without a
 * terminal assistant bubble. The UI renders the feedback controls on the run's
 * last assistant bubble (see {@link getRunScopedAnchorGroupIndices}), so the
 * anchor message is not necessarily the message that carries the field —
 * resolve by run_id instead of reading the anchor message directly.
 */
export function getFeedbackByRunId(
  groups: MessageGroup[],
): Map<string, FeedbackData> {
  const feedbackByRunId = new Map<string, FeedbackData>();
  for (const group of groups) {
    for (const message of group.messages) {
      const runId = getMessageRunId(message);
      const feedback = getMessageFeedback(message);
      if (runId && feedback) {
        feedbackByRunId.set(runId, feedback);
      }
    }
  }
  return feedbackByRunId;
}
