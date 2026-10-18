// Plain-language observations for a business owner, computed from their own weekly totals.
import { money, percent, shortDate } from "./format";
import type { CreditFile } from "./types";

export interface Insight {
  title: string;
  detail: string;
  tone: "green" | "amber" | "slate";
}

const average = (values: number[]) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;

export function insights(credit: CreditFile): Insight[] {
  const flow = credit.cash_flow;
  if (!flow || flow.weeks.length === 0) return [];
  const currency = flow.currency;
  const weeks = flow.weeks;
  const found: Insight[] = [];

  if (weeks.length >= 6) {
    const recent = average(weeks.slice(-4).map((w) => w.sales));
    const earlier = average(weeks.slice(0, -4).map((w) => w.sales));
    const change = earlier ? (recent - earlier) / earlier : 0;
    found.push({
      title:
        change > 0.05
          ? "Sales are rising"
          : change < -0.05
            ? "Sales are falling"
            : "Sales are flat",
      detail: `The last 4 weeks averaged ${money(recent, currency)} a week, ${percent(Math.abs(change))} ${change >= 0 ? "above" : "below"} the weeks before.`,
      tone: change < -0.05 ? "amber" : change > 0.05 ? "green" : "slate",
    });
  }

  const best = weeks.reduce((a, b) => (b.sales > a.sales ? b : a));
  const worst = weeks.reduce((a, b) => (b.sales < a.sales ? b : a));
  found.push({
    title: "Best and weakest weeks",
    detail: `Best: week of ${shortDate(best.week_start)} (${money(best.sales, currency)}). Weakest: week of ${shortDate(worst.week_start)} (${money(worst.sales, currency)}).`,
    tone: "slate",
  });

  if (flow.total_sales > 0) {
    const share = flow.total_expenses / flow.total_sales;
    found.push({
      title: share > 0.85 ? "Costs take most of your sales" : "You keep part of every sale",
      detail: `Expenses were ${percent(share)} of sales; you kept about ${money(flow.avg_weekly_net, currency)} a week.`,
      tone: share > 0.85 ? "amber" : "green",
    });
  }

  found.push({
    title: flow.sales_volatility < 0.2 ? "Steady sales" : "Sales swing week to week",
    detail:
      flow.sales_volatility < 0.2
        ? "Week-to-week sales vary little, which lenders read as lower risk."
        : `Weekly sales vary by about ${percent(flow.sales_volatility)}. Steadier records make a stronger case.`,
    tone: flow.sales_volatility < 0.2 ? "green" : "amber",
  });

  const flags = credit.consistency?.flags ?? [];
  if (flags.length > 0) {
    found.push({
      title: `${flags.length} week${flags.length === 1 ? "" : "s"} to explain`,
      detail: `Your notebook and wallet disagree in the week of ${flags.map((f) => shortDate(f.week_start)).join(", ")}. A lender will ask about ${flags.length === 1 ? "it" : "them"}.`,
      tone: "amber",
    });
  }

  const step = credit.risk?.path_to_approval[0];
  if (credit.risk) {
    found.push({
      title: `Loan readiness: grade ${credit.risk.grade}`,
      detail: step
        ? step.text
        : "Your records already support the loan you asked for. The lender makes the decision.",
      tone: ["A", "B"].includes(credit.risk.grade) ? "green" : "amber",
    });
  }
  return found;
}
