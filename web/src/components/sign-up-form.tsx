"use client";

import { createUserWithEmailAndPassword, updateProfile } from "@firebase/auth";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { writeSession } from "@/lib/firebase";
import type { OrgType } from "@/lib/types";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

// Markets with a rule pack; the list is public, so it is not fetched before sign-in.
const COUNTRIES = [
  { code: "lk", name: "Sri Lanka" },
  { code: "sg", name: "Singapore" },
  { code: "in", name: "India" },
];

const TYPES: { value: OrgType; label: string; note: string }[] = [
  { value: "business", label: "My business", note: "Start straight away." },
  { value: "lender", label: "A lender", note: "Starts once the platform approves it." },
  { value: "audit_firm", label: "An audit firm", note: "Starts once the platform approves it." },
];

/** Anyone signs up: a business starts at once; a lender or audit firm awaits approval. */
export function SignUpForm() {
  const { auth, refresh } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [type, setType] = useState<OrgType>("business");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setError(null);
    try {
      const { user } = await createUserWithEmailAndPassword(
        auth,
        value("email"),
        String(form.get("password")),
      );
      await updateProfile(user, { displayName: value("name") });
      await writeSession(user, true);
      await api.registerOrganisation(
        value("business_name"),
        value("type") as OrgType,
        value("jurisdiction") || null,
      );
      await refresh(); // picks up the owner role
      window.location.replace("/"); // a full load; see SignInForm
    } catch (e) {
      const code = (e as { code?: string }).code ?? "";
      setError(
        code === "auth/email-already-in-use"
          ? "An account with this email exists. Sign in instead."
          : code === "auth/weak-password"
            ? "Use a password of at least 8 characters."
            : (e as Error).message,
      );
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-4">
      <Card title="Create an account">
        <p className="mb-3 text-sm text-slate-600">
          Businesses upload their records, see their cash flow and choose who sees them. Lenders and
          audit firms work from the same evidence.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <fieldset className="space-y-1 text-sm">
            <legend className="mb-1 text-slate-600">I am signing up for</legend>
            {TYPES.map((t) => (
              <label key={t.value} className="flex items-start gap-2">
                <input
                  type="radio"
                  name="type"
                  value={t.value}
                  checked={type === t.value}
                  onChange={() => setType(t.value)}
                  className="mt-1"
                />
                <span>
                  {t.label} <span className="text-slate-500">· {t.note}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <Field label="Your name" name="name" autoComplete="name" />
          <Field
            label={type === "business" ? "Business name" : "Organisation name"}
            name="business_name"
          />
          <label className="block text-sm">
            <span className="text-slate-600">Country</span>
            <select
              name="jurisdiction"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {COUNTRIES.map((j) => (
                <option key={j.code} value={j.code}>
                  {j.name}
                </option>
              ))}
              <option value="">Other</option>
            </select>
          </label>
          <Field label="Email" name="email" type="email" autoComplete="email" />
          <Field
            label="Password (8 or more characters)"
            name="password"
            type="password"
            minLength={8}
            autoComplete="new-password"
          />
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy || !auth}>
            {busy ? "Creating…" : "Create account"}
          </Button>
        </form>
      </Card>
      <p className="text-center text-sm text-slate-600">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-emerald-700">
          Sign in
        </Link>
      </p>
    </div>
  );
}
