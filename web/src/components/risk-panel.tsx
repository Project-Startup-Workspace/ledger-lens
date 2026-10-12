import { percent } from "@/lib/format";
import type { RiskResult } from "@/lib/types";

import { Badge, Card, gradeTone, recommendationTone } from "./ui";

/** Grade, the reasons behind it, and what would change the outcome. */
export function RiskPanel({ risk }: { risk: RiskResult }) {
  const largest = Math.max(...risk.reasons.map((r) => Math.abs(r.contribution)), 0.01);
  return (
    <Card
      title="Risk"
      action={
        <Badge tone={recommendationTone(risk.recommendation)}>
          recommend {risk.recommendation}
        </Badge>
      }
    >
      <div className="mb-4 flex items-center gap-4">
        <div
          className={`flex h-16 w-16 items-center justify-center rounded-2xl text-3xl font-bold ring-1 ${gradeTone(risk.grade) === "green" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : gradeTone(risk.grade) === "amber" ? "bg-amber-50 text-amber-700 ring-amber-200" : "bg-rose-50 text-rose-700 ring-rose-200"}`}
        >
          {risk.grade}
        </div>
        <div className="text-sm">
          <p>Probability of default {percent(risk.probability_of_default, 1)}</p>
          <p className="text-xs text-slate-500">
            Model {risk.model_version}
            {risk.illustrative && " · illustrative, trained on synthetic data"}
          </p>
        </div>
      </div>
      <h3 className="mb-2 text-sm font-medium">Why</h3>
      <ul className="space-y-2">
        {risk.reasons.map((reason) => (
          <li key={reason.feature} className="text-sm">
            <p>{reason.text}</p>
            <div className="mt-1 h-1.5 rounded-full bg-slate-100">
              <div
                className={`h-1.5 rounded-full ${reason.contribution > 0 ? "bg-rose-400" : "bg-emerald-500"}`}
                style={{ width: `${(Math.abs(reason.contribution) / largest) * 100}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
      {risk.path_to_approval.length > 0 && (
        <>
          <h3 className="mb-2 mt-4 text-sm font-medium">Path to approval</h3>
          <ul className="space-y-2">
            {risk.path_to_approval.map((step) => (
              <li key={step.feature} className="flex items-start gap-2 text-sm">
                <span className="mt-0.5 text-emerald-600">→</span>
                <span>
                  {step.text}
                  {!step.sufficient && (
                    <span className="text-xs text-slate-500"> (helps, not enough alone)</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
