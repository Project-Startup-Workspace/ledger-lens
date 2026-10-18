"use client";

import { createUserWithEmailAndPassword, updateProfile } from "@firebase/auth";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { writeSession } from "@/lib/firebase";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

// Markets with a rule pack; the list is public, so it is not fetched before sign-in.
const COUNTRIES = [
  { code: "lk", name: "Sri Lanka" },
  { code: "sg", name: "Singapore" },
  { code: "in", name: "India" },
];

/** A business owner creates their own account; lenders and audit firms are invited. */
export function SignUpForm() {
  const { auth, refresh } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      await api.registerBusiness(value("business_name"), value("jurisdiction") || null);
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
      <Card title="Create a business account">
        <p className="mb-3 text-sm text-slate-600">
          Upload your notebook and wallet records, see your weekly cash flow, and choose which
          lender or auditor sees them.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Your name" name="name" autoComplete="name" />
          <Field label="Business name" name="business_name" />
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
