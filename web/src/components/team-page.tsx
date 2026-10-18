"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { roleLabel, shortDate } from "@/lib/format";
import type { AccessGrant, AuditLog, Member, Organisation, Role } from "@/lib/types";

import { useSession } from "./auth-provider";
import { Badge, Button, Card, ErrorNote, Field } from "./ui";

const ROLES: Partial<Record<string, Role[]>> = {
  lender: ["officer", "admin"],
  audit_firm: ["auditor", "admin"],
};

/** An organisation's admin: its people, which audit firms may see its cases, and its log. */
export function TeamPage() {
  const { me } = useSession();
  const [members, setMembers] = useState<Member[]>([]);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [firms, setFirms] = useState<Organisation[]>([]);
  const [log, setLog] = useState<AuditLog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const type = me?.org?.type;
  const roles = type ? ROLES[type] : undefined;
  const grantsAccess = type === "lender" || type === "business";

  const load = useCallback(
    () =>
      Promise.all([
        roles ? api.members() : Promise.resolve([]),
        api.grants(),
        grantsAccess ? api.organisations("audit_firm") : Promise.resolve([]),
        api.organisationAudit(),
      ])
        .then(([memberList, grantList, firmList, orgLog]) => {
          setMembers(memberList);
          setGrants(grantList);
          setFirms(firmList);
          setLog(orgLog);
        })
        .catch((e: Error) => setError(e.message)),
    [roles, grantsAccess],
  );

  useEffect(() => {
    if (me) load();
  }, [me, load]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await act(() =>
      api.addMember({
        email: String(data.get("email")).trim(),
        display_name: String(data.get("display_name")).trim(),
        password: String(data.get("password")),
        role: data.get("role") as Role,
      }),
    );
    form.reset();
  }

  if (!me?.org) return <p className="text-sm text-slate-500">Loading…</p>;
  const live = grants.filter((g) => !g.revoked_at);
  const ungranted = firms.filter((f) => !live.some((g) => g.grantee_org_id === f.id));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{me.org.name}</h1>
      <ErrorNote message={error} />
      {roles && (
        <Card title="People">
          <ul className="mb-4 divide-y divide-slate-100 text-sm">
            {members.map((m) => (
              <li key={m.uid} className="flex items-center justify-between gap-2 py-2">
                <span className={m.disabled ? "text-slate-400 line-through" : ""}>
                  {m.email} <span className="text-slate-500">· {roleLabel(m.role)}</span>
                </span>
                {!m.disabled && m.uid !== me.uid && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => act(() => api.removeMember(m.uid))}
                    className="text-xs text-rose-700"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
          <form onSubmit={addMember} className="space-y-3">
            <p className="text-sm font-medium">Add a colleague</p>
            <Field label="Email" name="email" type="email" />
            <Field label="Name" name="display_name" required={false} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Starting password" name="password" type="password" minLength={8} />
              <label className="block text-sm">
                <span className="text-slate-600">Role</span>
                <select
                  name="role"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                >
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {roleLabel(r)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <Button type="submit" disabled={busy}>
              Add
            </Button>
          </form>
        </Card>
      )}
      {grantsAccess && (
        <Card title="Audit firms with access">
          <p className="mb-3 text-sm text-slate-600">
            A firm you grant access sees, reviews and exports every case of{" "}
            {type === "business" ? "your business" : "your organisation"}, until you revoke it. Both
            are recorded.
          </p>
          <ul className="mb-3 space-y-2 text-sm">
            {live.length === 0 && <li className="text-slate-500">No firm has access.</li>}
            {live.map((g) => (
              <li key={g.id} className="flex items-center justify-between gap-2">
                <span>
                  <span className="font-medium">{g.grantee_name}</span>{" "}
                  <span className="text-slate-500">since {shortDate(g.granted_at)}</span>
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act(() => api.revoke(g.id))}
                  className="text-xs text-rose-700"
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            {ungranted.map((f) => (
              <Button
                key={f.id}
                variant="secondary"
                disabled={busy}
                onClick={() => act(() => api.grant(f.id))}
              >
                Grant {f.name}
              </Button>
            ))}
          </div>
        </Card>
      )}
      {log && (
        <Card
          title="Organisation log"
          action={
            <Badge tone={log.verification.valid ? "green" : "red"}>
              {log.verification.valid
                ? `chain intact · ${log.verification.events} events`
                : "chain broken"}
            </Badge>
          }
        >
          <ol className="max-h-56 space-y-1 overflow-y-auto font-mono text-xs">
            {log.events.map((event) => (
              <li key={event.seq}>
                {event.seq}. {event.event_type}{" "}
                <span className="text-slate-400">({event.actor})</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
