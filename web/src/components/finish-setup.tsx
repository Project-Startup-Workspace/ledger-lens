"use client";

import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

/** Signed in but not in an organisation yet: register a business, or wait for an invite. */
export function FinishSetup() {
  const { refresh } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("business_name")).trim();
    setBusy(true);
    try {
      await api.registerBusiness(name, null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
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
