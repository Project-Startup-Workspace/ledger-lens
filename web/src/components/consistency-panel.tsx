import { money, percent, shortDate } from "@/lib/format";
import type { ConsistencyReport } from "@/lib/types";

import { Badge, Card } from "./ui";

/** The fraud check: weeks where the notebook and the wallet disagree, and what to ask. */
export function ConsistencyPanel({
  report,
  currency,
}: {
  report: ConsistencyReport;
  currency: string;
}) {
  const verified = report.status === "compared";
  return (
    <Card
      title="Notebook vs wallet"
      action={
        verified ? (
          <Badge tone={report.flags.length ? "red" : "green"}>
            {report.flags.length ? `${report.flags.length} week(s) flagged` : "consistent"}
          </Badge>
        ) : (
          <Badge tone="amber">not verified</Badge>
        )
      }
    >
      {verified && report.baseline_ratio !== null && (
        <p className="mb-2 text-sm text-slate-600">
          {report.weeks_compared} weeks compared. Usually {percent(report.baseline_ratio)} of
          recorded sales reach the wallet.
        </p>
      )}
      <ul className="space-y-3">
        {report.flags.map((flag) => (
          <li
            key={flag.week_start}
            className="rounded-lg border border-rose-200 bg-rose-50/50 p-3 text-sm"
          >
            <div className="mb-1 flex items-center gap-2">
              <Badge tone={flag.severity === "high" ? "red" : "amber"}>{flag.severity}</Badge>
              <span className="font-medium">Week of {shortDate(flag.week_start)}</span>
            </div>
            <p className="text-slate-700">{flag.explanation}</p>
            <p className="mt-2 text-xs text-slate-500">
              Notebook {money(flag.notebook_sales, currency)} · wallet{" "}
              {money(flag.wallet_inflow, currency)}
            </p>
            <p className="mt-2 rounded bg-white p-2 italic">Ask: {flag.officer_question}</p>
          </li>
        ))}
      </ul>
      {report.notes.map((note) => (
        <p key={note} className="mt-2 text-xs text-slate-500">
          {note}
        </p>
      ))}
    </Card>
  );
}
