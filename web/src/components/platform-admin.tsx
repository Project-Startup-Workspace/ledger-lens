"use client";

import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { orgLabel } from "@/lib/format";
import type { Organisation, OrgType } from "@/lib/types";

import { Badge, Button, Card, ErrorNote, Field } from "./ui";

/** The platform admin adds lenders and audit firms, each with its first admin. */
export function PlatformAdmin() {
  const [orgs, setOrgs] = useState<Organisation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .organisations()
      .then(setOrgs)
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    setBusy(true);
    setError(null);
    try {
      await api.createOrganisation({
        name: value("name"),
        type: value("type") as OrgType,
        jurisdiction: value("jurisdiction") || null,
        admin: {
          email: value("email"),
          display_name: value("display_name"),
          password: String(data.get("password")),
        },
      });
      form.reset();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Organisations">
        <p className="mb-3 text-xs text-slate-500">
          The platform admin manages organisations and never sees their cases.
        </p>
        <ul className="divide-y divide-slate-100 text-sm">
          {orgs?.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2 py-2">
              <span className="font-medium">{o.name}</span>
              <Badge
                tone={o.type === "lender" ? "blue" : o.type === "business" ? "slate" : "green"}
              >
                {orgLabel(o.type)}
              </Badge>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Add a lender or audit firm">
        <form onSubmit={submit} className="space-y-3">
          <Field label="Organisation name" name="name" />
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="text-slate-600">Type</span>
              <select
                name="type"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value="lender">Lender</option>
                <option value="audit_firm">Audit firm</option>
              </select>
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Country</span>
              <select
                name="jurisdiction"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value="lk">Sri Lanka</option>
                <option value="sg">Singapore</option>
                <option value="in">India</option>
                <option value="">Other</option>
              </select>
            </label>
          </div>
          <p className="pt-2 text-sm font-medium">First admin</p>
          <Field label="Email" name="email" type="email" />
          <Field label="Name" name="display_name" required={false} />
          <Field label="Starting password" name="password" type="password" minLength={8} />
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add organisation"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
