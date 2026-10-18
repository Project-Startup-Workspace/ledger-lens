"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { CreditFile } from "@/lib/types";

import { Badge, Button, Card } from "./ui";

const PARTY = { lender: "the lender", business: "the business" };

/** Requests for evidence or explanations, and their answers, all in the audit trail. */
export function RequestsPanel({
  credit,
  askTo,
  answerAs,
  busy,
  run,
}: {
  credit: CreditFile;
  askTo: ("lender" | "business")[];
  answerAs: "lender" | "business" | null;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [to, setTo] = useState<"lender" | "business">(askTo[0] ?? "business");
  const [message, setMessage] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  if (credit.requests.length === 0 && askTo.length === 0) return null;

  return (
    <Card title="Requests">
      <ul className="mb-3 space-y-3 text-sm">
        {credit.requests.length === 0 && <li className="text-slate-500">No requests yet.</li>}
        {credit.requests.map((r) => (
          <li key={r.id} className="rounded-lg bg-slate-50 p-3">
            <p>
              <Badge tone={r.answer ? "green" : "amber"}>{r.answer ? "answered" : "open"}</Badge>{" "}
              <span className="text-slate-500">
                {r.requested_by} asked {PARTY[r.addressed_to]} on {shortDate(r.created_at)}
              </span>
            </p>
            <p className="mt-1">{r.message}</p>
            {r.answer && (
              <p className="mt-1 text-slate-700">
                <span className="text-slate-500">{r.answered_by}:</span> {r.answer}
              </p>
            )}
            {!r.answer && answerAs === r.addressed_to && (
              <div className="mt-2 flex gap-2">
                <input
                  value={answers[r.id] ?? ""}
                  onChange={(e) => setAnswers({ ...answers, [r.id]: e.target.value })}
                  placeholder={
                    r.addressed_to === "business"
                      ? "Your answer (add any file under Evidence first)"
                      : "Your answer"
                  }
                  className="flex-1 rounded-lg border border-slate-300 px-2 py-1"
                />
                <Button
                  variant="secondary"
                  disabled={busy || !answers[r.id]?.trim()}
                  onClick={() => run(() => api.answer(credit.case_id, r.id, answers[r.id]))}
                >
                  Answer
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {askTo.length > 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-600">Ask</span>
            <select
              value={to}
              onChange={(e) => setTo(e.target.value as "lender" | "business")}
              className="rounded-lg border border-slate-300 px-2 py-1"
            >
              {askTo.map((party) => (
                <option key={party} value={party}>
                  {PARTY[party]}
                </option>
              ))}
            </select>
          </div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="What you need, e.g. the wallet statement for September"
            rows={2}
            className="w-full rounded-lg border border-slate-300 p-2 text-sm"
          />
          <Button
            variant="secondary"
            disabled={busy || !message.trim()}
            onClick={() =>
              run(async () => {
                await api.ask(credit.case_id, to, message);
                setMessage("");
              })
            }
          >
            Send request
          </Button>
        </div>
      )}
    </Card>
  );
}
