import { money, percent, shortDate } from "@/lib/format";
import type { CashFlowSummary, ConsistencyFlag } from "@/lib/types";

import { Card } from "./ui";

/** Weekly sales and expenses as bars; weeks flagged by the consistency check are marked. */
export function CashFlowPanel({
  flow,
  flags,
}: {
  flow: CashFlowSummary;
  flags: ConsistencyFlag[];
}) {
  const flagged = new Set(flags.map((f) => f.week_start));
  const max = Math.max(1, ...flow.weeks.flatMap((w) => [w.sales, w.expenses]));
  const barWidth = 100 / Math.max(flow.weeks.length, 1);

  return (
    <Card title="Weekly cash flow">
      <div className="mb-3 grid grid-cols-3 gap-2 text-center">
        <Stat label="Avg sales / week" value={money(flow.avg_weekly_sales, flow.currency)} />
        <Stat label="Avg net / week" value={money(flow.avg_weekly_net, flow.currency)} />
        <Stat label="Sales swing" value={percent(flow.sales_volatility)} />
      </div>
      <svg
        viewBox="0 0 100 50"
        className="h-44 w-full"
        role="img"
        aria-label="Weekly sales and expenses"
      >
        {flow.weeks.map((week, i) => {
          const x = i * barWidth;
          const salesH = (week.sales / max) * 44;
          const costH = (week.expenses / max) * 44;
          return (
            <g key={week.week_start}>
              {flagged.has(week.week_start) && (
                <rect x={x} y={0} width={barWidth} height={46} className="fill-rose-100" />
              )}
              <rect
                x={x + barWidth * 0.15}
                y={46 - salesH}
                width={barWidth * 0.33}
                height={salesH}
                className="fill-emerald-500"
              >
                <title>{`${week.iso_week} sales ${money(week.sales, flow.currency)}`}</title>
              </rect>
              <rect
                x={x + barWidth * 0.52}
                y={46 - costH}
                width={barWidth * 0.33}
                height={costH}
                className="fill-slate-400"
              >
                <title>{`${week.iso_week} expenses ${money(week.expenses, flow.currency)}`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>{flow.weeks[0] && shortDate(flow.weeks[0].week_start)}</span>
        <span className="flex gap-3">
          <span className="text-emerald-600">■ sales</span>
          <span className="text-slate-500">■ expenses</span>
          {flagged.size > 0 && <span className="text-rose-500">■ flagged week</span>}
        </span>
        <span>{flow.weeks.at(-1) && shortDate(flow.weeks.at(-1)!.week_start)}</span>
      </div>
      {flow.entries_for_review.length > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
          {flow.entries_for_review.length} line(s) could not be read confidently and are left out of
          these totals until checked.
        </p>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  );
}
