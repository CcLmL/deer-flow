import { PencilIcon, ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  deleteFeedback,
  upsertFeedback,
  type FeedbackData,
} from "@/core/api/feedback";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { Tooltip } from "../tooltip";

const FEEDBACK_CATEGORY_KEYS = [
  "incorrectOrIncomplete",
  "slowOrBuggy",
  "styleOrTone",
  "safetyOrLegalConcerns",
  "outofdateMessage",
  "other",
] as const;

type FeedbackCategoryKey = (typeof FEEDBACK_CATEGORY_KEYS)[number];

/**
 * Compose the stored comment from the selected category and the free-text
 * details. The backend stores one `comment` string per (thread, run), so the
 * category is persisted as plain text rather than a structured field: the
 * localized category label is wrapped in a `~label~` marker line ahead of the
 * details so it can be split back out when editing.
 */
function buildFeedbackComment(
  category: string | null,
  details: string,
): string | null {
  const trimmed = details.trim();
  if (category) {
    return trimmed ? `~${category}~\n${trimmed}` : `~${category}~`;
  }
  return trimmed || null;
}

type ParsedFeedbackComment = {
  category: FeedbackCategoryKey | null;
  details: string;
};

/**
 * Split a stored comment back into its category and free-text details.
 *
 * Marker rows resolve against the *current* locale's labels; an unresolved
 * marker (e.g. saved under another locale) is kept verbatim as free text
 * rather than silently dropped. Legacy rows — a bare string equal to one
 * category label, or any other plain text — degrade to a selected category
 * with empty details, or details only.
 */
function parseFeedbackComment(
  comment: string | null,
  labels: Record<FeedbackCategoryKey, string>,
): ParsedFeedbackComment {
  if (!comment) {
    return { category: null, details: "" };
  }
  const marker = /^~([^~\n]+)~\n?([\s\S]*)$/.exec(comment);
  if (marker) {
    const label = marker[1];
    const key = FEEDBACK_CATEGORY_KEYS.find(
      (candidate) => labels[candidate] === label,
    );
    if (key) {
      return { category: key, details: marker[2] ?? "" };
    }
    return { category: null, details: comment };
  }
  const bareLabelKey = FEEDBACK_CATEGORY_KEYS.find(
    (candidate) => labels[candidate] === comment,
  );
  if (bareLabelKey) {
    return { category: bareLabelKey, details: "" };
  }
  return { category: null, details: comment };
}

/**
 * Run-scoped feedback controls rendered in the assistant message's hover
 * action row, after the regenerate button. Clicking a thumb opens the
 * feedback dialog (category + optional details); the submit stores rating and
 * comment together through one upsert. Clicking the active thumb deletes the
 * feedback, and the edit button reopens the dialog with the current rating
 * and saved comment prefilled.
 */
export function MessageFeedback({
  threadId,
  runId,
  initialFeedback,
}: {
  threadId: string;
  runId: string;
  initialFeedback: FeedbackData | null;
}) {
  const { t } = useI18n();
  const [feedback, setFeedback] = useState<FeedbackData | null>(
    initialFeedback,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingRating, setPendingRating] = useState<number | null>(null);
  const [category, setCategory] = useState<FeedbackCategoryKey | null>(null);
  const [details, setDetails] = useState("");

  const categories = useMemo(
    () =>
      FEEDBACK_CATEGORY_KEYS.map((key) => ({
        key,
        label: t.feedback.categories[key],
      })),
    [t.feedback.categories],
  );

  // Display the saved comment as `category\n details` without the internal
  // `~label~` marker.
  const displayedComment = useMemo(() => {
    const parsed = parseFeedbackComment(
      feedback?.comment ?? null,
      t.feedback.categories,
    );
    if (parsed.category && parsed.details) {
      return `${t.feedback.categories[parsed.category]}\n${parsed.details}`;
    }
    if (parsed.category) {
      return t.feedback.categories[parsed.category];
    }
    return parsed.details;
  }, [feedback, t.feedback.categories]);

  const openDialog = useCallback(
    (rating: number) => {
      // Split the saved comment back into its category and free-text details:
      // the matching category button re-selects and the textarea carries only
      // the comment, so editing does not silently drop or duplicate either.
      const parsed = parseFeedbackComment(
        feedback?.comment ?? null,
        t.feedback.categories,
      );
      setCategory(parsed.category);
      setDetails(parsed.details);
      setPendingRating(rating);
      setDialogOpen(true);
    },
    [feedback, t.feedback.categories],
  );

  const handleSubmit = useCallback(async () => {
    if (pendingRating === null || isSubmitting) return;
    const comment = buildFeedbackComment(
      category ? t.feedback.categories[category] : null,
      details,
    );
    setIsSubmitting(true);
    try {
      const result = await upsertFeedback(
        threadId,
        runId,
        pendingRating,
        comment ?? undefined,
      );
      setFeedback(result);
      setDialogOpen(false);
    } catch {
      // Revert on error — feedback state unchanged on catch
    } finally {
      setIsSubmitting(false);
    }
  }, [
    category,
    details,
    isSubmitting,
    pendingRating,
    runId,
    t.feedback.categories,
    threadId,
  ]);

  const handleDelete = useCallback(async () => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    try {
      await deleteFeedback(threadId, runId);
      setFeedback(null);
    } catch {
      // Revert on error — feedback state unchanged on catch
    } finally {
      setIsSubmitting(false);
    }
  }, [isSubmitting, runId, threadId]);

  const handleThumbClick = useCallback(
    (rating: number) => {
      if (feedback?.rating === rating) {
        void handleDelete();
        return;
      }
      openDialog(rating);
    },
    [feedback, handleDelete, openDialog],
  );

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1">
        <Tooltip content={t.feedback.helpful}>
          <Button
            aria-label={t.feedback.helpful}
            aria-pressed={feedback?.rating === 1}
            size="icon-sm"
            type="button"
            variant="ghost"
            disabled={isSubmitting}
            onClick={() => handleThumbClick(1)}
          >
            <ThumbsUpIcon
              className={cn("size-3", feedback?.rating === 1 && "fill-current")}
            />
          </Button>
        </Tooltip>
        <Tooltip content={t.feedback.notHelpful}>
          <Button
            aria-label={t.feedback.notHelpful}
            aria-pressed={feedback?.rating === -1}
            size="icon-sm"
            type="button"
            variant="ghost"
            disabled={isSubmitting}
            onClick={() => handleThumbClick(-1)}
          >
            <ThumbsDownIcon
              className={cn(
                "size-3",
                feedback?.rating === -1 && "fill-current",
              )}
            />
          </Button>
        </Tooltip>
        {feedback && (
          <Tooltip content={t.feedback.editComment}>
            <Button
              aria-label={t.feedback.editComment}
              size="icon-sm"
              type="button"
              variant="ghost"
              disabled={isSubmitting}
              onClick={() => openDialog(feedback.rating)}
            >
              <PencilIcon className="size-3" />
            </Button>
          </Tooltip>
        )}
      </div>
      {displayedComment && (
        <p className="text-muted-foreground max-w-[20rem] text-xs break-words whitespace-pre-wrap">
          {displayedComment}
        </p>
      )}
      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open && !isSubmitting) {
            setDialogOpen(false);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t.feedback.shareFeedback}</DialogTitle>
            <DialogDescription className="sr-only">
              {t.feedback.detailsLabel}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            {categories.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                aria-pressed={category === key}
                className={cn(
                  "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  category === key
                    ? "bg-accent border-foreground/30"
                    : "hover:bg-accent/60 border-border",
                )}
                onClick={() => setCategory(category === key ? null : key)}
              >
                {label}
              </button>
            ))}
          </div>
          <Textarea
            aria-label={t.feedback.detailsLabel}
            className="mt-3 resize-none"
            onChange={(event) => setDetails(event.currentTarget.value)}
            placeholder={t.feedback.detailsPlaceholder}
            rows={3}
            value={details}
          />
          <DialogFooter className="mt-3">
            <Button
              disabled={isSubmitting}
              onClick={() => setDialogOpen(false)}
              type="button"
              variant="outline"
            >
              {t.common.cancel}
            </Button>
            <Button
              disabled={isSubmitting}
              onClick={() => void handleSubmit()}
              type="button"
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
