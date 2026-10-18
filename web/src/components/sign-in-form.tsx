"use client";

import { sendPasswordResetEmail, signInWithEmailAndPassword } from "@firebase/auth";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

const PARTIES = [
  {
    who: "Business owners",
    what: "Photograph the notebook, see weekly cash flow and loan readiness, choose who sees it.",
  },
  {
    who: "Lenders",
    what: "Loan officers prepare each application; a credit reviewer decides, with reasons.",
  },
  {
    who: "Audit firms",
    what: "Check the evidence behind every number and approve a signed audit report.",
  },
];

/** Only same-site paths, so a crafted link cannot send someone elsewhere after sign-in. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function SignInForm() {
  const next = safeNext(useSearchParams().get("next"));
  const { auth, me, ready } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");

  // A full load, not a client navigation: pages prefetched before sign-in hold the
  // redirect to this page, and the router would replay it.
  useEffect(() => {
    if (me) window.location.replace(next);
  }, [me, next]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await signInWithEmailAndPassword(auth, email.trim(), String(form.get("password")));
      // The session provider loads the person and the effect above moves on.
    } catch {
      setError("That email and password do not match an account.");
      setBusy(false);
    }
  }

  async function resetPassword() {
    if (!auth) return;
    setError(null);
    if (!email.trim()) {
      setError("Enter your email first, then choose “Forgot password?”.");
      return;
    }
    try {
      await sendPasswordResetEmail(auth, email.trim());
    } catch {
      // Same answer either way, so the form does not reveal which emails have accounts.
    }
    setNotice(`If ${email.trim()} has an account, a link to set a new password is on its way.`);
  }

  if (ready && !auth) return <p className="text-sm text-slate-600">Sign-in is not needed here.</p>;
  return (
    <div className="grid gap-6 md:grid-cols-2 md:items-center">
      <section className="space-y-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Everyday records, turned into evidence everyone can trust.
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Ledger Lens reads a microbusiness&apos;s notebook and wallet in its own language, and
            gives the owner, the lender and the auditor one shared, traceable record.
          </p>
        </div>
        <ul className="space-y-3">
          {PARTIES.map((p) => (
            <li key={p.who} className="flex gap-3 text-sm">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
              <span>
                <span className="font-medium">{p.who}.</span>{" "}
                <span className="text-slate-600">{p.what}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
      <div className="space-y-4">
        <Card title="Sign in">
          <form onSubmit={submit} className="space-y-3">
            <Field
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e: { target: HTMLInputElement }) => setEmail(e.target.value)}
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="current-password"
            />
            <ErrorNote message={error} />
            {notice && (
              <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>
            )}
            <div className="flex items-center justify-between gap-2">
              <Button type="submit" disabled={busy || !auth}>
                {busy ? "Signing in…" : "Sign in"}
              </Button>
              <button
                type="button"
                onClick={resetPassword}
                className="text-sm text-slate-600 hover:text-slate-900"
              >
                Forgot password?
              </button>
            </div>
          </form>
        </Card>
        <p className="text-center text-sm text-slate-600">
          New here?{" "}
          <Link href="/signup" className="font-medium text-emerald-700">
            Create an account
          </Link>{" "}
          for your business, lender or audit firm.
        </p>
      </div>
    </div>
  );
}
