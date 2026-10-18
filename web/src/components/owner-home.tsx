"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { insights } from "@/lib/insights";
import type { CaseSummary, CreditFile, Organisation } from "@/lib/types";

import { useSession } from "./auth-provider";
import { CashFlowPanel } from "./cash-flow-panel";
import { Badge, Card, ErrorNote } from "./ui";

/** A business owner's own records: insights first, then their applications and who sees them. */
export function OwnerHome() {
  const { me } = useSession();
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [latest, setLatest] = useState<CreditFile | null>(null);
  const [lenders, setLenders] = useState<Organisation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listCases(), api.organisations("lender")])
      .then(async ([list, lenderList]) => {
        setCases(list);
        setLenders(lenderList);
        const assessed = list.find((c) => c.grade !== null);
        if (assessed) setLatest(await api.getCase(assessed.case_id));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const lenderName = (id: string | null) => lenders.find((l) => l.id === id)?.name ?? "a lender";
  const found = latest ? insights(latest) : [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{me?.org?.name}</h1>
        <p className="text-sm text-slate-600">
          Your records, what they show, and who you have shared them with.
        </p>
      </div>
      <ErrorNote message={error} />
      {cases?.length === 0 && (
        <Card title="Start with your records">
          <p className="text-sm text-slate-600">
            Open an application, photograph a few weeks of your notebook and add your wallet
            statement. Ledger Lens reads them and shows your weekly cash flow. Nothing is shared
            until you send it to a lender.
          </p>
          <Link
            href="/cases/new"
            className="mt-3 inline-block rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white"
          >
            Start an application
          </Link>
        </Card>
      )}
      {found.length > 0 && (
        <Card title="Insights from your records">
          <ul className="space-y-3">
            {found.map((item) => (
              <li key={item.title} className="text-sm">
                <Badge tone={item.tone}>{item.title}</Badge>
                <p className="mt-1 text-slate-700">{item.detail}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-slate-500">
            From “{latest?.applicant.business_name}”, your latest assessed application.
          </p>
        </Card>
      )}
      {latest?.cash_flow && (
        <CashFlowPanel flow={latest.cash_flow} flags={latest.consistency?.flags ?? []} />
      )}
      {cases && cases.length > 0 && (
        <Card title="Your applications">
          <ul className="divide-y divide-slate-100">
            {cases.map((c) => (
              <li key={c.case_id}>
                <Link
                  href={`/cases/${c.case_id}`}
                  className="flex items-center justify-between gap-3 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{money(c.amount, c.currency)}</p>
                    <p className="text-xs text-slate-500">
                      {c.lender_org_id
                        ? `Sent to ${lenderName(c.lender_org_id)}`
                        : "Private: only you can see it"}{" "}
                      · {c.status}
                    </p>
                  </div>
                  {c.grade && <Badge tone="slate">Grade {c.grade}</Badge>}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
