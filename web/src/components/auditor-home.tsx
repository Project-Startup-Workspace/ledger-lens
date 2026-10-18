"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { AccessGrant } from "@/lib/types";

import { useSession } from "./auth-provider";
import { CaseList } from "./case-list";
import { Badge, Card, ErrorNote } from "./ui";

/** An audit firm sees exactly the organisations that granted it access, and their cases. */
export function AuditorHome() {
  const { me } = useSession();
  const officer = me?.role === "audit_officer";
  const [grants, setGrants] = useState<AccessGrant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .grants()
      .then(setGrants)
      .catch((e: Error) => setError(e.message));
  }, []);

  const live = grants?.filter((g) => !g.revoked_at) ?? [];
  return (
    <div className="space-y-4">
      <ErrorNote message={error} />
      <Card title="Access granted to your firm">
        {grants && live.length === 0 && (
          <p className="text-sm text-slate-500">
            No organisation has granted access yet. Lenders and businesses grant it from their
            Sharing or Team page.
          </p>
        )}
        <ul className="space-y-2 text-sm">
          {live.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-2">
              <span className="font-medium">{g.grantor_name}</span>
              <Badge tone="green">since {shortDate(g.granted_at)}</Badge>
            </li>
          ))}
        </ul>
      </Card>
      <CaseList
        title={officer ? "Your engagements" : "Cases your firm can audit"}
        demos={false}
        empty={
          officer
            ? "Your firm's admin assigns engagements to you."
            : "Cases appear here once an organisation grants your firm access."
        }
      />
    </div>
  );
}
