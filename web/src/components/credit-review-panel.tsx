"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { CreditFile, Member } from "@/lib/types";

import { Button, Card } from "./ui";

/** Four eyes: the loan officer prepares, a credit reviewer decides. */
export function CreditReviewPanel({
  credit,
  canAssign,
  busy,
  run,
}: {
  credit: CreditFile;
  canAssign: boolean;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [reviewers, setReviewers] = useState<Member[]>([]);
  const [choice, setChoice] = useState("");
  const review = credit.credit_review;

  useEffect(() => {
    if (!canAssign) return;
    api
      .colleagues("credit_reviewer")
      .then((list) => {
        setReviewers(list);
        setChoice((current) => current || list[0]?.uid || "");
      })
      .catch(() => setReviewers([]));
  }, [canAssign]);

  if (!review && !canAssign) return null;
  return (
    <Card title="Credit review">
      {review && (
        <p className="mb-2 text-sm text-slate-700">
          With <span className="font-medium">{review.reviewer}</span> since{" "}
          {shortDate(review.requested_at)}, sent by {review.requested_by}.
        </p>
      )}
      {canAssign && !credit.decision && (
        <div className="flex flex-wrap gap-2 text-sm">
          {reviewers.length === 0 ? (
            <p className="text-slate-500">Your organisation has no credit reviewer yet.</p>
          ) : (
            <>
              <select
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                {reviewers.map((r) => (
                  <option key={r.uid} value={r.uid}>
                    {r.display_name || r.email}
                  </option>
                ))}
              </select>
              <Button
                variant="secondary"
                disabled={busy || !choice}
                onClick={() => run(() => api.assignReviewer(credit.case_id, choice))}
              >
                {review ? "Reassign" : "Send for credit review"}
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
