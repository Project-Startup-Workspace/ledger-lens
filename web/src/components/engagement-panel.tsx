"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { CasePermissions } from "@/lib/permissions";
import type { CreditFile, Engagement, Member } from "@/lib/types";

import { Badge, Button, Card, type Tone } from "./ui";

const STATUS_TONE: Record<Engagement["status"], Tone> = {
  open: "blue",
  submitted: "amber",
  returned: "red",
  approved: "green",
};

/** An audit firm's engagement: assigned, worked, reviewed and approved as the report. */
export function EngagementPanel({
  credit,
  can,
  busy,
  run,
}: {
  credit: CreditFile;
  can: CasePermissions;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [officers, setOfficers] = useState<Member[]>([]);
  const [assignee, setAssignee] = useState("");
  const [severity, setSeverity] = useState<"observation" | "issue">("observation");
  const [note, setNote] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const id = credit.case_id;

  useEffect(() => {
    if (!can.assignEngagement) return;
    api
      .colleagues("audit_officer")
      .then((list) => {
        setOfficers(list);
        setAssignee((current) => current || list[0]?.uid || "");
      })
      .catch(() => setOfficers([]));
  }, [can.assignEngagement]);

  if (credit.engagements.length === 0 && !can.assignEngagement) return null;
  return (
    <Card title="Audit engagements">
      <ul className="mb-3 space-y-3 text-sm">
        {credit.engagements.map((e) => (
          <li key={e.id} className="rounded-lg bg-slate-50 p-3">
            <p>
              <Badge tone={STATUS_TONE[e.status]}>
                {e.status === "approved" ? "report approved" : e.status}
              </Badge>{" "}
              <span className="text-slate-500">
                {e.assignee}, assigned by {e.assigned_by} on {shortDate(e.assigned_at)}
              </span>
            </p>
            <ul className="mt-2 space-y-1">
              {e.findings.map((f) => (
                <li key={f.id}>
                  <Badge tone={f.severity === "issue" ? "amber" : "slate"}>{f.severity}</Badge>{" "}
                  {f.note}{" "}
                  <span className="font-mono text-xs text-slate-400">
                    {f.snapshot.slice(0, 10)}
                  </span>
                </li>
              ))}
            </ul>
            {e.reviewed_by && (
              <p className="mt-2 text-slate-600">
                {e.status === "approved" ? "Approved" : "Returned"} by {e.reviewed_by}
                {e.review_note ? `: “${e.review_note}”` : ""}
              </p>
            )}
            {can.approveReport && e.status === "submitted" && (
              <div className="mt-2 space-y-2">
                <input
                  value={reviewNote}
                  onChange={(ev) => setReviewNote(ev.target.value)}
                  placeholder="Reviewer's note"
                  className="w-full rounded-lg border border-slate-300 px-2 py-1"
                />
                <div className="flex gap-2">
                  <Button
                    disabled={busy}
                    onClick={() => run(() => api.reviewEngagement(id, e.id, true, reviewNote))}
                  >
                    Approve final report
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={busy || !reviewNote.trim()}
                    onClick={() => run(() => api.reviewEngagement(id, e.id, false, reviewNote))}
                  >
                    Return for more work
                  </Button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
      {can.assignEngagement && (
        <div className="flex flex-wrap gap-2 text-sm">
          {officers.length === 0 ? (
            <p className="text-slate-500">Add an audit officer on the Team page first.</p>
          ) : (
            <>
              <select
                value={assignee}
                onChange={(ev) => setAssignee(ev.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                {officers.map((o) => (
                  <option key={o.uid} value={o.uid}>
                    {o.display_name || o.email}
                  </option>
                ))}
              </select>
              <Button
                variant="secondary"
                disabled={busy || !assignee}
                onClick={() => run(() => api.assignEngagement(id, assignee))}
              >
                Assign engagement
              </Button>
            </>
          )}
        </div>
      )}
      {can.engagement && (
        <div className="space-y-2">
          <div className="flex gap-2">
            {(["observation", "issue"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setSeverity(value)}
                className={`flex-1 rounded-lg py-2 text-sm capitalize ring-1 ${severity === value ? "bg-slate-900 text-white ring-slate-900" : "ring-slate-300"}`}
              >
                {value}
              </button>
            ))}
          </div>
          <textarea
            value={note}
            onChange={(ev) => setNote(ev.target.value)}
            placeholder="What you checked and what you found"
            rows={3}
            className="w-full rounded-lg border border-slate-300 p-2 text-sm"
          />
          <div className="flex gap-2">
            <Button
              disabled={busy || !note.trim()}
              onClick={() =>
                run(async () => {
                  await api.addFinding(id, severity, note);
                  setNote("");
                })
              }
            >
              Record finding
            </Button>
            <Button
              variant="secondary"
              disabled={busy || can.engagement.findings.length === 0}
              onClick={() => run(() => api.submitFindings(id))}
            >
              Submit for review
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
