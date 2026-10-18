"use client";

import Link from "next/link";

import { orgLabel, roleLabel } from "@/lib/format";

import { useSession } from "./auth-provider";

/** Brand, the actions this person's role allows, and who is signed in. */
export function SiteHeader() {
  const { me, auth, signOut } = useSession();
  const type = me?.org?.type;
  const active = me?.org?.status === "active";
  const canOpenCases =
    active &&
    (type === "business" ||
      (type === "lender" && ["admin", "loan_officer"].includes(me?.role ?? "")));
  const manages = active && (me?.role === "admin" || me?.role === "owner");
  return (
    <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          Ledger <span className="text-emerald-600">Lens</span>
        </Link>
        <nav className="flex flex-wrap items-center gap-2 text-sm">
          {manages && (
            <Link href="/team" className="rounded-lg px-2 py-1.5 text-slate-700 hover:bg-slate-100">
              {type === "business" ? "Team & sharing" : "Team & access"}
            </Link>
          )}
          {canOpenCases && (
            <Link
              href="/cases/new"
              className="rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white"
            >
              {type === "business" ? "New application" : "New case"}
            </Link>
          )}
          {auth && me && (
            <button
              type="button"
              onClick={signOut}
              className="rounded-lg px-2 py-1.5 text-slate-600 hover:bg-slate-100"
              title={me.email}
            >
              Sign out
            </button>
          )}
        </nav>
      </div>
      {auth && me?.org && (
        <p className="mx-auto max-w-3xl px-4 pb-2 text-xs text-slate-500">
          {me.email} · {roleLabel(me.role)} · {me.org.name} ({orgLabel(me.org.type)})
        </p>
      )}
    </header>
  );
}
