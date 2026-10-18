"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { LANGUAGES } from "@/lib/languages";
import type { Jurisdiction } from "@/lib/types";

import { useSession } from "./auth-provider";
import { Button, Card, ErrorNote, Field } from "./ui";

export function NewCaseForm() {
  const router = useRouter();
  const { me } = useSession();
  // An owner applies for themselves: their own consent, their business's name.
  const owner = me?.org?.type === "business";
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);

  useEffect(() => {
    api
      .jurisdictions()
      .then(setJurisdictions)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setSaving(true);
    try {
      const created = await api.createCase({
        jurisdiction: value("jurisdiction"),
        consent_given: form.get("consent") === "on",
        applicant: {
          full_name: value("full_name"),
          date_of_birth: value("date_of_birth"),
          national_id: value("national_id"),
          phone: value("phone"),
          business_name: value("business_name"),
          business_type: value("business_type"),
          years_in_business: Number(value("years_in_business")),
          preferred_language: value("preferred_language"),
          guarantor_name: value("guarantor_name") || null,
        },
        loan: {
          amount: Number(value("amount")),
          currency: value("currency").toUpperCase(),
          tenor_months: Number(value("tenor_months")),
          annual_rate_pct: Number(value("annual_rate_pct")),
          purpose: value("purpose"),
        },
      });
      router.push(`/cases/${created.case_id}`);
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Card title={owner ? "About you and your business" : "Applicant"}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Full name" name="full_name" />
          <Field label="Date of birth" name="date_of_birth" type="date" />
          <Field label="National ID" name="national_id" />
          <Field label="Phone" name="phone" type="tel" />
          <Field
            label="Business name"
            name="business_name"
            defaultValue={owner ? me?.org?.name : undefined}
          />
          <Field label="Business type" name="business_type" placeholder="grocery shop" />
          <Field
            label="Years in business"
            name="years_in_business"
            type="number"
            min="0"
            step="0.5"
          />
          <Field label="Guarantor (optional)" name="guarantor_name" required={false} />
          <label className="block text-sm">
            <span className="text-slate-600">Preferred language</span>
            <select
              name="preferred_language"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {Object.entries(LANGUAGES).map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>
      <Card title="Loan request">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Amount" name="amount" type="number" min="1" />
          <Field label="Currency" name="currency" placeholder="LKR" maxLength={3} />
          <Field label="Tenor (months)" name="tenor_months" type="number" min="1" max="120" />
          <Field
            label="Annual rate (%)"
            name="annual_rate_pct"
            type="number"
            min="0"
            max="100"
            step="0.1"
          />
          <Field label="Purpose" name="purpose" />
          <label className="block text-sm">
            <span className="text-slate-600">Jurisdiction</span>
            <select
              name="jurisdiction"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {jurisdictions.map((j) => (
                <option key={j.code} value={j.code}>
                  {j.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>
      <label className="flex items-start gap-2 rounded-2xl border border-slate-200 bg-white p-4 text-sm">
        <input type="checkbox" name="consent" required className="mt-1" />
        <span>
          {owner
            ? "I agree that my notebook and statements may be read to assess this loan. Nothing is shared until I send it to a lender."
            : "The applicant has agreed that their notebook and statements may be read to assess this loan."}
        </span>
      </label>
      <ErrorNote message={error} />
      <Button type="submit" disabled={saving}>
        {saving ? "Creating…" : owner ? "Start application" : "Create case"}
      </Button>
    </form>
  );
}
