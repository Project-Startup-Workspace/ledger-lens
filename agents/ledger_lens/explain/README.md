# Explanation agent

| | |
|---|---|
| Input | An assessed `CreditFile`, optional target language |
| Output | `Explanation` (borrower text, language, who wrote it); `officer_report(case)` Markdown; WAV audio on request |
| Models | `LL_MODEL_REASON` for the borrower text, `LL_MODEL_TTS` for speech |

- **Officer report.** Built from the current case whenever it is needed (screen, audit pack), so it reflects the latest compliance results and decision. It includes every evidence warning and consistency note.
- **Borrower text.** Gemini writes it in one of the supported languages (`prompts.LANGUAGES`) from a short list of checked facts (`borrower_facts`). No personal identifiers or raw document text reach the prompt.
- **Guardrails on output.** Text that is empty, too long, flagged by the safety screen, or that contains a number not in the facts is discarded, and the English template is used instead. `written_by` records the model and prompt version, or `template`.
- **Speech.** Gemini TTS, only for languages with a known TTS locale (`prompts.TTS_LOCALES`), and only when `LL_ENABLE_TTS` is on and a Gemini provider is configured.
