"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { ComplianceReport, FindingStatus, Jurisdiction } from "@/lib/types";

import { Badge, Card, ErrorNote, type Tone } from "./ui";

const STATUS: Record<FindingStatus, { tone: Tone; label: string }> = {
  pass: { tone: "green", label: "pass" },
  fail: { tone: "red", label: "fail" },
  review: { tone: "amber", label: "review" },
  pending: { tone: "slate", label: "pending" },
  not_applicable: { tone: "slate", label: "n/a" },
};

/** AuditPulse: switch jurisdiction to see the same case under another regulator's rules. */
export function CompliancePanel({
  caseId,
  initial,
}: {
  caseId: string;
  initial: ComplianceReport;
}) {
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);
  const [report, setReport] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0); // only the most recent switch may update the panel

  useEffect(() => {
    api
      .jurisdictions()
      .then(setJurisdictions)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function switchTo(code: string) {
    const request = ++latest.current;
    setError(null);
    try {
      const next = code === initial.jurisdiction ? initial : await api.compliance(caseId, code);
      if (request === latest.current) setReport(next);
    } catch (e) {
      if (request === latest.current) setError((e as Error).message);
    }
  }

  return (
    <Card title="Compliance (AuditPulse)">
      <div className="mb-3 flex gap-1 rounded-lg bg-slate-100 p-1">
        {jurisdictions.map((j) => (
          <button
            key={j.code}
            onClick={() => switchTo(j.code)}
            className={`flex-1 rounded-md px-2 py-1.5 text-sm ${report.jurisdiction === j.code ? "bg-white font-medium shadow-sm" : "text-slate-600"}`}
          >
            {j.name}
          </button>
        ))}
      </div>
      <ErrorNote message={error} />
      <p className="mb-2 text-xs text-slate-500">Rule packs {report.rule_pack_version}</p>
      <ul className="divide-y divide-slate-100">
        {report.findings.map((finding) => (
          <li key={finding.rule_id} className="py-2">
            <details>
              <summary className="flex cursor-pointer list-none items-start justify-between gap-2 text-sm">
                <span>
                  <span className="font-mono text-xs text-slate-400">{finding.rule_id}</span>{" "}
                  {finding.title}
                </span>
                <Badge tone={STATUS[finding.status].tone}>{STATUS[finding.status].label}</Badge>
              </summary>
              <div className="mt-2 space-y-2 text-sm text-slate-600">
                <p>{finding.detail}</p>
                {finding.citations.map((c) => (
                  <blockquote
                    key={c.title + c.clause}
                    className="border-l-2 border-slate-300 pl-3 text-xs"
                  >
                    <p>{c.excerpt}</p>
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sky-700 underline"
                    >
                      {c.title} · {c.clause}
                    </a>
                  </blockquote>
                ))}
              </div>
            </details>
          </li>
        ))}
      </ul>
    </Card>
  );
}
