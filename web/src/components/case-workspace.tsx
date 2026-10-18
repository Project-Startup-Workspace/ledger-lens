"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { permissions } from "@/lib/permissions";
import { money } from "@/lib/format";
import type { CreditFile } from "@/lib/types";

import { CashFlowPanel } from "./cash-flow-panel";
import { CompliancePanel } from "./compliance-panel";
import { ConsistencyPanel } from "./consistency-panel";
import { DecisionPanel } from "./decision-panel";
import { EvidencePanel } from "./evidence-panel";
import { ExplanationPanel } from "./explanation-panel";
import { useSession } from "./auth-provider";
import { ReviewPanel } from "./review-panel";
import { RiskPanel } from "./risk-panel";
import { SharingPanel } from "./sharing-panel";
import { Badge, Button, ErrorNote } from "./ui";

/** One case, top to bottom in the order an officer works: evidence, checks, decision. */
export function CaseWorkspace() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const [credit, setCredit] = useState<CreditFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => api.getCase(id).then(setCredit), [id]);

  useEffect(() => {
    reload().catch((e: Error) => setError(e.message));
  }, [reload]);

  async function run(action: () => Promise<CreditFile | unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result && typeof result === "object" && "case_id" in result)
        setCredit(result as CreditFile);
      else await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!credit)
    return error ? (
      <ErrorNote message={error} />
    ) : (
      <p className="text-sm text-slate-500">Loading case…</p>
    );

  const assessed = credit.status !== "draft";
  const can = permissions(me, credit);
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{credit.applicant.business_name}</h1>
          <Badge tone={credit.status === "decided" ? "blue" : "slate"}>{credit.status}</Badge>
        </div>
        <p className="text-sm text-slate-600">
          {credit.applicant.business_type} · {credit.applicant.years_in_business} years · asks{" "}
          {money(credit.loan.amount, credit.loan.currency)} over {credit.loan.tenor_months} months
        </p>
      </div>
      <ErrorNote message={error} />
      {credit.business_org_id && (
        <SharingPanel credit={credit} canSend={can.send} busy={busy} run={run} />
      )}
      <EvidencePanel
        credit={credit}
        busy={busy}
        onUpload={can.prepare ? (kind, file) => run(() => api.upload(id, kind, file)) : undefined}
      />
      {can.prepare && (
        <Button
          disabled={busy || credit.evidence.length === 0}
          onClick={() => run(() => api.assess(id))}
        >
          {busy ? "Working…" : assessed ? "Reassess" : "Assess"}
        </Button>
      )}
      {credit.cash_flow && (
        <CashFlowPanel flow={credit.cash_flow} flags={credit.consistency?.flags ?? []} />
      )}
      {credit.consistency && (
        <ConsistencyPanel report={credit.consistency} currency={credit.loan.currency} />
      )}
      {credit.risk && <RiskPanel risk={credit.risk} />}
      {/* Keyed by revision: a saved change to the case resets these panels' local state. */}
      {credit.compliance && (
        <CompliancePanel key={credit.revision} caseId={id} initial={credit.compliance} />
      )}
      {credit.explanation && (
        <ExplanationPanel
          key={credit.revision}
          caseId={id}
          initial={credit.explanation}
          canChange={can.explain}
        />
      )}
      {assessed && (
        <DecisionPanel
          key={credit.revision}
          credit={credit}
          busy={busy}
          run={run}
          canDecide={can.decide}
        />
      )}
      <ReviewPanel credit={credit} canReview={can.review} busy={busy} run={run} />
    </div>
  );
}
