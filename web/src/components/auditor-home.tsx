"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { grantLive, grantPending } from "@/lib/permissions";
import type { AccessGrant } from "@/lib/types";

import { useSession } from "./auth-provider";
import { CaseList } from "./case-list";
import { Badge, Button, Card, ErrorNote } from "./ui";

/** An audit firm answers requests to audit, and sees the organisations that it accepted,
 * and their cases. */
export function AuditorHome() {
  const { me } = useSession();
  const officer = me?.role === "audit_officer";
  const admin = me?.role === "admin";
  const [grants, setGrants] = useState<AccessGrant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      api
        .grants()
        .then(setGrants)
        .catch((e: Error) => setError(e.message)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  async function respond(grant: AccessGrant, accept: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.respondToGrant(grant.id, accept);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const live = grants?.filter((g) => grantLive(g)) ?? [];
  const pending = grants?.filter(grantPending) ?? [];
  return (
    <div className="space-y-4">
      <ErrorNote message={error} />
      {pending.length > 0 && (
        <Card title="Requests to audit">
          <p className="mb-3 text-sm text-slate-600">
            {admin
              ? "Accepting lets your firm see every case of that organisation until it revokes access."
              : "Your firm's admin accepts or declines these."}
          </p>
          <ul className="space-y-2 text-sm">
            {pending.map((g) => (
              <li key={g.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="font-medium">{g.grantor_name}</span>{" "}
                  <span className="text-slate-500">asked {shortDate(g.granted_at)}</span>
                </span>
                {admin && (
                  <span className="flex gap-2">
                    <Button disabled={busy} onClick={() => respond(g, true)}>
                      Accept
                    </Button>
                    <Button variant="secondary" disabled={busy} onClick={() => respond(g, false)}>
                      Decline
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Access granted to your firm">
        {grants && live.length === 0 && (
          <p className="text-sm text-slate-500">
            No organisation has granted access yet. Lenders and businesses ask from their Team page;
            your firm&apos;s admin accepts.
          </p>
        )}
        <ul className="space-y-2 text-sm">
          {live.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-2">
              <span className="font-medium">{g.grantor_name}</span>
              <Badge tone="green">since {shortDate(g.responded_at ?? g.granted_at)}</Badge>
            </li>
          ))}
        </ul>
      </Card>
      {/* Keyed by the accepted organisations, so the list reloads after an answer. */}
      <CaseList
        key={live.map((g) => g.id).join()}
        title={officer ? "Your engagements" : "Cases your firm can audit"}
        demos={false}
        empty={
          officer
            ? "Your firm's admin assigns engagements to you."
            : "Cases appear here once your firm accepts a request to audit."
        }
      />
    </div>
  );
}
