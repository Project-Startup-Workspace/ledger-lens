"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { CreditFile } from "@/lib/types";

import { Badge, Button, Card } from "./ui";

/** Audit firms record their review against the case exactly as it stood. */
export function ReviewPanel({
  credit,
  canReview,
  busy,
  run,
}: {
  credit: CreditFile;
  canReview: boolean;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [outcome, setOutcome] = useState<"no_issues" | "issues_found">("no_issues");
  const [note, setNote] = useState("");
  if (!canReview && credit.reviews.length === 0) return null;

  return (
    <Card title="Audit reviews">
      <ul className="mb-3 space-y-2 text-sm">
        {credit.reviews.length === 0 && <li className="text-slate-500">No review yet.</li>}
        {credit.reviews.map((r) => (
          <li key={r.id}>
            <Badge tone={r.outcome === "no_issues" ? "green" : "amber"}>
              {r.outcome === "no_issues" ? "no issues" : "issues found"}
            </Badge>{" "}
            by <span className="font-medium">{r.reviewer}</span> on {shortDate(r.reviewed_at)}
            <p className="text-slate-600">“{r.note}”</p>
            <p className="font-mono text-xs text-slate-400">snapshot {r.snapshot.slice(0, 12)}</p>
          </li>
        ))}
      </ul>
      {canReview && (
        <div className="space-y-3">
          <div className="flex gap-2">
            {(["no_issues", "issues_found"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setOutcome(value)}
                className={`flex-1 rounded-lg py-2 text-sm ring-1 ${outcome === value ? "bg-slate-900 text-white ring-slate-900" : "ring-slate-300"}`}
              >
                {value === "no_issues" ? "No issues" : "Issues found"}
              </button>
            ))}
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What you checked and what you found"
            rows={3}
            className="w-full rounded-lg border border-slate-300 p-2 text-sm"
          />
          <Button
            disabled={busy || !note.trim()}
            onClick={() => run(() => api.review(credit.case_id, outcome, note))}
          >
            Record review
          </Button>
        </div>
      )}
    </Card>
  );
}
