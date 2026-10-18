"use client";

import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

/** Signed in but not in an organisation: register a business, wait for an invitation, or
 * wait for the platform to approve a lender or audit firm. */
export function FinishSetup() {
  const { me, refresh } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("business_name")).trim();
    setBusy(true);
    try {
      await api.registerOrganisation(name, "business", null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (me?.org && me.org.status !== "active") {
    return (
      <Card title={me.org.name}>
        <p className="text-sm text-slate-700">
          {me.org.status === "pending"
            ? "Your organisation is waiting for the platform's approval. You can invite colleagues and start work as soon as it is approved."
            : "Your organisation is suspended. Contact the platform to reinstate it."}
        </p>
      </Card>
    );
  }
  return (
    <Card title="Finish setting up">
      <p className="mb-3 text-sm text-slate-600">
        Lender and audit firm staff are added by their organisation&apos;s admin. If you run a
        business, register it to start.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Business name" name="business_name" />
        <ErrorNote message={error} />
        <Button type="submit" disabled={busy}>
          Register my business
        </Button>
      </form>
    </Card>
  );
}
