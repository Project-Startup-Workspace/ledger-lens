# Explanation agent

| | |
|---|---|
| Input | An assessed `CreditFile`, optional target language |
| Output | `Explanation`: Markdown officer report and borrower text; WAV audio on request |
| Models | `LL_MODEL_REASON` for the borrower text, `LL_MODEL_TTS` for speech |

- The officer report is assembled from agent outputs only, so it cannot contain a claim no agent made.
- The borrower text is written by Gemini from a short list of checked facts (`borrower_facts`). Raw document text never reaches the prompt, so instructions hidden in a photo cannot steer it.
- Offline, or if the model fails, the borrower text falls back to an English template and `translated` is false.
- Speech uses Gemini TTS and can be turned off with `LL_ENABLE_TTS=false`.
