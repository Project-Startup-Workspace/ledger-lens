"use client";

import { useEffect, useState } from "react";

import { api, urls } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import type { AuditLog, CreditFile, Outcome } from "@/lib/types";

import { Badge, Button, Card, ErrorNote, recommendationTone } from "./ui";

/** The officer decides; the system records who, what, why, and seals it in the audit trail. */
export function DecisionPanel({
  credit,
  busy,
  run,
  canDecide,
}: {
  credit: CreditFile;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
  /** Only the lender's staff decide; everyone else sees the outcome when it is recorded. */
  canDecide: boolean;
}) {
  const id = credit.case_id;
  const [outcome, setOutcome] = useState<Outcome>(credit.risk?.recommendation ?? "refer");
  const [reason, setReason] = useState("");
  const [audit, setAudit] = useState<AuditLog | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function exportPack() {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await api.exportAuditPack(id);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `audit-pack-${id}.zip`;
      link.click();
      // Revoke later: some browsers read the blob after click() returns.
      setTimeout(() => URL.revokeObjectURL(link.href), 60_000);
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setExporting(false);
      // Whatever happened, the chain may have changed (the export is recorded in it).
      api
        .audit(id)
        .then(setAudit)
        .catch(() => undefined);
    }
  }
  const disclosure = credit.disclosure;
  const decision = credit.decision;
  const overriding = credit.risk && outcome !== credit.risk.recommendation;

  useEffect(() => {
    api
      .audit(id)
      .then(setAudit)
      .catch(() => setAudit(null));
  }, [id, credit.revision]);

  return (
    <>
      {disclosure && (
        <Card title="Key Fact Statement">
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-slate-500">APR</dt>
            <dd>{disclosure.apr_pct}%</dd>
            <dt className="text-slate-500">Instalment</dt>
            <dd>
              {money(disclosure.instalment, credit.loan.currency)} × {disclosure.instalments}
            </dd>
            <dt className="text-slate-500">Total repayable</dt>
            <dd>{money(disclosure.total_repayable, credit.loan.currency)}</dd>
          </dl>
          <div className="mt-3">
            {disclosure.acknowledged_at ? (
              <Badge tone="green">acknowledged {shortDate(disclosure.acknowledged_at)}</Badge>
            ) : (
              !decision &&
              canDecide && (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => run(() => api.acknowledge(id))}
                >
                  Borrower has read and acknowledged it
                </Button>
              )
            )}
          </div>
        </Card>
      )}
      <Card title="Decision">
        {decision ? (
          <div className="space-y-1 text-sm">
            <p>
              <Badge tone={recommendationTone(decision.outcome)}>{decision.outcome}</Badge> by{" "}
              <span className="font-medium">{decision.officer_id}</span> on{" "}
              {shortDate(decision.decided_at)}
            </p>
            {decision.overridden && (
              <p className="text-amber-700">
                Overrides the recommendation ({decision.recommended}).
              </p>
            )}
            <p className="text-slate-600">“{decision.reason}”</p>
          </div>
        ) : !canDecide ? (
          <p className="text-sm text-slate-500">Waiting for the lender&apos;s decision.</p>
        ) : (
          <div className="space-y-3">
            <div className="flex gap-2">
              {(["approve", "refer", "decline"] as const).map((value) => (
                <button
                  key={value}
                  onClick={() => setOutcome(value)}
                  className={`flex-1 rounded-lg py-2 text-sm capitalize ring-1 ${outcome === value ? "bg-slate-900 text-white ring-slate-900" : "ring-slate-300"}`}
                >
                  {value}
                </button>
              ))}
            </div>
            {overriding && (
              <p className="text-xs text-amber-700">
                This differs from the recommendation ({credit.risk?.recommendation}). Your reason is
                recorded.
              </p>
            )}
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for the decision"
              rows={3}
              className="w-full rounded-lg border border-slate-300 p-2 text-sm"
            />
            <Button
              disabled={busy || !reason.trim()}
              onClick={() => run(() => api.decide(id, outcome, reason))}
            >
              Record decision
            </Button>
          </div>
        )}
      </Card>
      <Card
        title="Audit trail"
        action={
          audit && (
            <Badge tone={audit.verification.valid ? "green" : "red"}>
              {audit.verification.valid
                ? `chain intact · ${audit.verification.events} events`
                : "chain broken"}
            </Badge>
          )
        }
      >
        <ol className="max-h-56 space-y-1 overflow-y-auto font-mono text-xs">
          {audit?.events.map((event) => (
            <li key={event.seq} className="flex justify-between gap-2">
              <span>
                {event.seq}. {event.event_type}{" "}
                <span className="text-slate-400">({event.actor})</span>
              </span>
              <span className="text-slate-400">{event.hash.slice(0, 10)}</span>
            </li>
          ))}
        </ol>
        <ErrorNote message={exportError} />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={exporting}
            onClick={exportPack}
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {exporting ? "Exporting…" : "Export audit pack"}
          </button>
          <a
            href={urls.report(id)}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300"
          >
            Officer report
          </a>
        </div>
      </Card>
    </>
  );
}
