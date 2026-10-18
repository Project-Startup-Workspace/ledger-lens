"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { money, title } from "@/lib/format";
import type { CaseSummary } from "@/lib/types";

import { Badge, Button, Card, ErrorNote, gradeTone } from "./ui";

export function CaseList() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [demos, setDemos] = useState<string[]>([]);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listCases(), api.demoCases()])
      .then(([caseList, demoList]) => {
        setCases(caseList);
        setDemos(demoList);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function openDemo(slug: string) {
    setOpening(slug);
    try {
      const created = await api.openDemo(slug);
      router.push(`/cases/${created.case_id}`);
    } catch (e) {
      setError((e as Error).message);
      setOpening(null);
    }
  }

  return (
    <div className="space-y-4">
      <ErrorNote message={error} />
      <Card title="Demo cases">
        <p className="mb-3 text-sm text-slate-600">
          Synthetic notebooks in Bahasa Indonesia, Sinhala and Vietnamese. Each opens a new case
          with its pages and statement uploaded.
        </p>
        <div className="flex flex-wrap gap-2">
          {demos.map((slug) => (
            <Button
              key={slug}
              variant="secondary"
              disabled={opening !== null}
              onClick={() => openDemo(slug)}
            >
              {opening === slug ? "Opening…" : title(slug)}
            </Button>
          ))}
        </div>
      </Card>
      <Card title="Cases">
        {cases === null && !error && <p className="text-sm text-slate-500">Loading…</p>}
        {cases?.length === 0 && <p className="text-sm text-slate-500">No cases yet.</p>}
        <ul className="divide-y divide-slate-100">
          {cases?.map((c) => (
            <li key={c.case_id}>
              <Link
                href={`/cases/${c.case_id}`}
                className="flex items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{c.business_name}</p>
                  <p className="text-xs text-slate-500">
                    {money(c.amount, c.currency)} · {c.jurisdiction.toUpperCase()} · {c.status}
                  </p>
                </div>
                {c.grade && <Badge tone={gradeTone(c.grade)}>Grade {c.grade}</Badge>}
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
