"use client";

import { useState } from "react";

import { api, urls } from "@/lib/api";
import { LANGUAGES } from "@/lib/languages";
import type { Explanation } from "@/lib/types";

import { Badge, Button, Card, ErrorNote } from "./ui";

/** What the borrower hears: plain words in their language, read aloud where possible. */
export function ExplanationPanel({ caseId, initial }: { caseId: string; initial: Explanation }) {
  const [explanation, setExplanation] = useState(initial);
  const [language, setLanguage] = useState(initial.borrower_language);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function translate(code: string) {
    setLanguage(code);
    setBusy(true);
    setError(null);
    try {
      setExplanation(await api.explain(caseId, code));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function readInBrowser() {
    // Fallback when server speech is off: the device's own voice, if it has one.
    const utterance = new SpeechSynthesisUtterance(explanation.borrower_text);
    utterance.lang = explanation.borrower_language;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  return (
    <Card
      title="For the borrower"
      action={
        <select
          value={language}
          disabled={busy}
          onChange={(e) => translate(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
        >
          {Object.entries(LANGUAGES).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      }
    >
      <ErrorNote message={error} />
      {!explanation.translated && (
        <p className="mb-2 text-xs text-amber-700">
          Shown in English: translation needs a Gemini connection.
        </p>
      )}
      <p className="whitespace-pre-line text-sm leading-relaxed">
        {busy ? "Writing…" : explanation.borrower_text}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {explanation.audio_available ? (
          // Keyed and versioned by language so a translation reloads the audio, and
          // preload="none" so speech is only generated when someone presses play.
          <audio
            key={explanation.borrower_language}
            controls
            preload="none"
            src={urls.audio(caseId, explanation.borrower_language)}
            className="w-full"
          />
        ) : (
          <Button variant="secondary" onClick={readInBrowser}>
            Read aloud on this device
          </Button>
        )}
        <Badge>{explanation.written_by}</Badge>
      </div>
    </Card>
  );
}
