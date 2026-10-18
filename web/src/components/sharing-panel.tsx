"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { CreditFile, Organisation } from "@/lib/types";

import { Button, Card } from "./ui";

/** The owner's application stays private until they choose a lender to send it to. */
export function SharingPanel({
  credit,
  canSend,
  busy,
  run,
}: {
  credit: CreditFile;
  canSend: boolean;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [lenders, setLenders] = useState<Organisation[]>([]);
  const [choice, setChoice] = useState("");

  useEffect(() => {
    api
      .organisations("lender")
      .then((list) => {
        setLenders(list);
        setChoice((current) => current || list[0]?.id || "");
      })
      .catch(() => setLenders([]));
  }, []);

  const sentTo = lenders.find((l) => l.id === credit.lender_org_id)?.name;
  return (
    <Card title="Who sees this application">
      {credit.lender_org_id ? (
        <p className="text-sm text-slate-700">
          Sent to <span className="font-medium">{sentTo ?? "a lender"}</span>. Their staff now work
          it and make the decision; you keep seeing every step.
        </p>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-slate-700">
            Private: only you can see it. Assess it first to see what a lender will see, then send
            it.
          </p>
          {canSend && lenders.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <select
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                {lenders.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
              <Button
                disabled={busy || !choice || credit.evidence.length === 0}
                onClick={() => run(() => api.sendApplication(credit.case_id, choice))}
              >
                Send to lender
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
