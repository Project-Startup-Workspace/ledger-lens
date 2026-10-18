"use client";

import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { orgLabel } from "@/lib/format";
import type { Organisation, OrgStatus, OrgType, PlatformSettings } from "@/lib/types";

import { Badge, Button, Card, ErrorNote, Field } from "./ui";

const STATUS_TONE = { active: "green", pending: "amber", suspended: "red" } as const;

/** The platform admin approves organisations, adds lenders and audit firms, and runs
 * the platform's settings. Cases stay out of sight unless support access is granted. */
export function PlatformAdmin() {
  const [orgs, setOrgs] = useState<Organisation[] | null>(null);
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [cap, setCap] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    Promise.all([api.organisations(), api.platformSettings()])
      .then(([orgList, current]) => {
        setOrgs(orgList);
        setSettings(current);
        // Only the first load fills the box, so a reload never overwrites what is typed.
        setCap((typed) => typed || String(current.effective_daily_model_calls));
      })
      .catch((e: Error) => setError(e.message));

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
  const setStatus = (org: Organisation, status: OrgStatus) =>
    act(() => api.setOrganisationStatus(org.id, status));
  useEffect(() => {
    load();
  }, []);

  async function addAdmin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await act(() =>
      api.addOrganisationAdmin(String(data.get("org_id")), {
        email: String(data.get("email")).trim(),
        display_name: String(data.get("display_name")).trim(),
        password: String(data.get("password")),
      }),
    );
    form.reset();
  }

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
      <ErrorNote message={error} />
      <Card title="Organisations">
        <p className="mb-3 text-xs text-slate-500">
          Lenders and audit firms that sign up wait here for approval. The platform never sees cases
          unless an organisation grants support access.
        </p>
        <ul className="divide-y divide-slate-100 text-sm">
          {orgs?.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <span className="font-medium">{o.name}</span>{" "}
                <span className="text-slate-500">· {orgLabel(o.type)}</span>
              </span>
              <span className="flex items-center gap-2">
                <Badge tone={STATUS_TONE[o.status]}>{o.status}</Badge>
                {o.type !== "platform" && o.status !== "active" && (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setStatus(o, "active")}
                  >
                    {o.status === "pending" ? "Approve" : "Reinstate"}
                  </Button>
                )}
                {o.type !== "platform" && o.status !== "suspended" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setStatus(o, "suspended")}
                    className="text-xs text-rose-700"
                  >
                    Suspend
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      {settings && (
        <Card title="Platform settings">
          <dl className="mb-3 grid grid-cols-2 gap-2 text-sm">
            <dt className="text-slate-500">Gemini calls today</dt>
            <dd>
              {settings.model_calls_today ?? "not counted (offline models)"}
              {settings.effective_daily_model_calls > 0 &&
                ` of ${settings.effective_daily_model_calls}`}
            </dd>
            <dt className="text-slate-500">Models</dt>
            <dd className="break-all">
              {settings.model_extract}, {settings.model_reason}
            </dd>
          </dl>
          <div className="flex flex-wrap items-end gap-2">
            <label className="block text-sm">
              <span className="text-slate-600">Daily Gemini call cap (0 = no cap)</span>
              <input
                type="number"
                min="0"
                value={cap}
                onChange={(e) => setCap(e.target.value)}
                className="mt-1 w-32 rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
            <Button
              variant="secondary"
              disabled={busy || cap === ""}
              onClick={() =>
                act(() => api.updatePlatformSettings({ daily_model_calls: Number(cap) }))
              }
            >
              Save cap
            </Button>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.config.self_registration}
              disabled={busy}
              onChange={(e) =>
                act(() => api.updatePlatformSettings({ self_registration: e.target.checked }))
              }
            />
            Lenders and audit firms may sign up and apply for approval
          </label>
          <p className="mt-2 text-xs text-slate-500">
            The deployment default cap is {settings.deployment_daily_model_calls}
            {settings.config.updated_by && `; last changed by ${settings.config.updated_by}`}.
          </p>
        </Card>
      )}
      <Card title="Add an admin to an organisation">
        <form onSubmit={addAdmin} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-600">Organisation</span>
            <select
              name="org_id"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {orgs
                ?.filter((o) => o.type !== "platform")
                .map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name} ({orgLabel(o.type)})
                  </option>
                ))}
            </select>
          </label>
          <Field label="Email" name="email" type="email" />
          <Field label="Name" name="display_name" required={false} />
          <Field label="Starting password" name="password" type="password" minLength={8} />
          <Button type="submit" disabled={busy}>
            Add admin
          </Button>
        </form>
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
          <Button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add organisation"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
