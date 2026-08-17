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

const FEEDBACK_CATEGORY_KEYS = [
  "incorrectOrIncomplete",
  "slowOrBuggy",
  "styleOrTone",
  "safetyOrLegalConcerns",
  "other",
] as const;

type FeedbackCategoryKey = (typeof FEEDBACK_CATEGORY_KEYS)[number];

/**
 * Compose the stored comment from the selected category and the free-text
 * details. The backend stores one `comment` string per (thread, run), so the
 * category is persisted as plain text rather than a structured field.
 */
function buildFeedbackComment(
  category: string | null,
  details: string,
): string | null {
  const trimmed = details.trim();
  if (category && trimmed) {
    return `${category}\n${trimmed}`;
  }
  if (category) {
    return category;
  }
  return trimmed || null;
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

  const openDialog = useCallback(
    (rating: number) => {
      // Prefill the free-text details with the existing comment so editing
      // does not silently drop the previously saved text. The category is not
      // parsed back out of the stored string — the saved comment is one text.
      setDetails(feedback?.comment ?? "");
      setCategory(null);
      setPendingRating(rating);
      setDialogOpen(true);
    },
    [feedback],
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

  const thumbButtonClass = (active: boolean) =>
    cn(
      "text-muted-foreground hover:text-foreground rounded-md p-1 transition-colors",
      active && "text-foreground",
    );

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t.feedback.helpful}
          aria-pressed={feedback?.rating === 1}
          className={thumbButtonClass(feedback?.rating === 1)}
          onClick={() => handleThumbClick(1)}
          disabled={isSubmitting}
        >
          <ThumbsUpIcon
            className={cn("size-4", feedback?.rating === 1 && "fill-current")}
          />
        </button>
        <button
          type="button"
          aria-label={t.feedback.notHelpful}
          aria-pressed={feedback?.rating === -1}
          className={thumbButtonClass(feedback?.rating === -1)}
          onClick={() => handleThumbClick(-1)}
          disabled={isSubmitting}
        >
          <ThumbsDownIcon
            className={cn("size-4", feedback?.rating === -1 && "fill-current")}
          />
        </button>
        {feedback && (
          <button
            type="button"
            aria-label={t.feedback.editComment}
            className="text-muted-foreground hover:text-foreground rounded-md p-1 transition-colors"
            onClick={() => openDialog(feedback.rating)}
            disabled={isSubmitting}
          >
            <PencilIcon className="size-3" />
          </button>
        )}
      </div>
      {feedback?.comment && (
        <p className="text-muted-foreground max-w-[20rem] text-xs break-words whitespace-pre-wrap">
          {feedback.comment}
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
