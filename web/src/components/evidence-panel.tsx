"use client";

import { useState } from "react";

import { urls } from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import type { CreditFile } from "@/lib/types";

import { Badge, Card } from "./ui";

// What the API accepts (agents/ledger_lens/api/app.py ALLOWED_TYPES).
const PAGE_TYPES = "image/png,image/jpeg,image/webp";
const STATEMENT_TYPES = ".csv,text/csv,image/png,image/jpeg,image/webp,application/pdf";

/** Upload pages (camera on phones) and see every figure boxed where it was read. */
export function EvidencePanel({
  credit,
  busy,
  onUpload,
}: {
  credit: CreditFile;
  busy: boolean;
  onUpload: (kind: string, file: File) => void;
}) {
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<string | null>(null);
  // Until the officer picks a document, show the latest photo (boxes are what matter),
  // falling back to the latest upload of any kind.
  const latestImage = credit.evidence.findLast((d) => d.content_type.startsWith("image/"));
  const doc =
    credit.evidence.find((d) => d.id === selectedDoc) ?? latestImage ?? credit.evidence.at(-1);
  const extraction = credit.extractions.find((x) => x.evidence_id === doc?.id);
  // The server decides what needs review (its threshold is configurable), not the UI.
  const forReview = new Set(credit.cash_flow?.entries_for_review.map((e) => e.id));
  const isImage = doc?.content_type.startsWith("image/");
  const closed = credit.status === "decided";

  return (
    <Card title={`Evidence (${credit.evidence.length})`}>
      {!closed && (
        <div className="mb-3 flex flex-wrap gap-2">
          <UploadButton
            label="Photograph notebook page"
            accept={PAGE_TYPES}
            capture
            disabled={busy}
            onPick={(f) => onUpload("notebook", f)}
          />
          <UploadButton
            label="Add wallet statement"
            accept={STATEMENT_TYPES}
            disabled={busy}
            onPick={(f) => onUpload("wallet_statement", f)}
          />
        </div>
      )}
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {credit.evidence.map((d) => (
          <button
            key={d.id}
            onClick={() => setSelectedDoc(d.id)}
            className={`shrink-0 rounded-lg px-3 py-1.5 text-xs ring-1 ${d.id === doc?.id ? "bg-slate-900 text-white ring-slate-900" : "bg-white ring-slate-300"}`}
          >
            {d.filename}
          </button>
        ))}
      </div>
      {doc && isImage && (
        <div className="relative overflow-hidden rounded-lg ring-1 ring-slate-200">
          {/* eslint-disable-next-line @next/next/no-img-element -- authenticated proxy URL, not optimisable */}
          <img
            src={urls.evidenceFile(credit.case_id, doc.id)}
            alt={doc.filename}
            className="w-full"
          />
          {extraction?.entries.map((entry) =>
            entry.box ? (
              <button
                key={entry.id}
                aria-label={`${entry.description} ${entry.amount}`}
                onClick={() => setSelectedEntry(entry.id)}
                className={`absolute rounded-sm ring-2 transition ${boxStyle(forReview.has(entry.id), entry.id === selectedEntry)}`}
                style={{
                  left: `${entry.box.x_min * 100}%`,
                  top: `${entry.box.y_min * 100}%`,
                  width: `${(entry.box.x_max - entry.box.x_min) * 100}%`,
                  height: `${(entry.box.y_max - entry.box.y_min) * 100}%`,
                }}
              />
            ) : null,
          )}
        </div>
      )}
      {extraction && (
        <>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <Badge>{extraction.script}</Badge>
            <Badge>{extraction.entries.length} lines</Badge>
            <Badge tone="slate">{extraction.model}</Badge>
          </div>
          {extraction.warnings.map((w) => (
            <p key={w} className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
              {w}
            </p>
          ))}
          <ul className="mt-3 max-h-64 divide-y divide-slate-100 overflow-y-auto text-sm">
            {extraction.entries.map((entry) => (
              <li
                key={entry.id}
                onClick={() => setSelectedEntry(entry.id)}
                className={`flex cursor-pointer justify-between gap-2 px-1 py-1.5 ${entry.id === selectedEntry ? "bg-sky-50" : ""}`}
              >
                <span className="truncate">
                  {shortDate(entry.entry_date)} · {entry.description}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {forReview.has(entry.id) && <Badge tone="amber">review</Badge>}
                  <span className={entry.direction === "in" ? "text-emerald-700" : "text-rose-700"}>
                    {entry.direction === "in" ? "+" : "−"}
                    {money(entry.amount, extraction.currency)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {doc && !extraction && <p className="text-sm text-slate-500">Not read yet. Press Assess.</p>}
    </Card>
  );
}

function boxStyle(needsReview: boolean, selected: boolean): string {
  if (selected) return "bg-sky-400/30 ring-sky-500";
  if (needsReview) return "bg-amber-300/30 ring-amber-500";
  return "ring-emerald-500/60 hover:bg-emerald-300/20";
}

function UploadButton({
  label,
  accept,
  capture,
  disabled,
  onPick,
}: {
  label: string;
  accept: string;
  capture?: boolean;
  disabled: boolean;
  onPick: (file: File) => void;
}) {
  return (
    <label
      className={`cursor-pointer rounded-lg bg-white px-3 py-2 text-sm font-medium ring-1 ring-slate-300 ${disabled ? "opacity-50" : "hover:bg-slate-50"}`}
    >
      {label}
      <input
        type="file"
        accept={accept}
        capture={capture ? "environment" : undefined}
        disabled={disabled}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onPick(file);
          event.target.value = "";
        }}
      />
    </label>
  );
}
