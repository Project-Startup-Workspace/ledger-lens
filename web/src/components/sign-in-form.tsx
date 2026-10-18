"use client";

import { signInWithEmailAndPassword } from "@firebase/auth";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

/** Only same-site paths, so a crafted link cannot send someone elsewhere after sign-in. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function SignInForm() {
  const next = safeNext(useSearchParams().get("next"));
  const { auth, me, ready } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    try {
      await signInWithEmailAndPassword(
        auth,
        String(form.get("email")).trim(),
        String(form.get("password")),
      );
      // The session provider loads the person and the effect above moves on.
    } catch {
      setError("That email and password do not match an account.");
      setBusy(false);
    }
  }

  if (ready && !auth) return <p className="text-sm text-slate-600">Sign-in is not needed here.</p>;
  return (
    <div className="mx-auto max-w-sm space-y-4">
      <Card title="Sign in">
        <p className="mb-3 text-sm text-slate-600">
          One place for business owners, lenders and audit firms to work from the same evidence.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Email" name="email" type="email" autoComplete="email" />
          <Field label="Password" name="password" type="password" autoComplete="current-password" />
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy || !auth}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
      <p className="text-center text-sm text-slate-600">
        Run a small business?{" "}
        <Link href="/signup" className="font-medium text-emerald-700">
          Create a free account
        </Link>
      </p>
    </div>
  );
}
