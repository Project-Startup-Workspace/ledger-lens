"""Prompts for borrower explanations. Only structured, already-checked facts go in:
never raw text from uploaded documents, which could carry injected instructions."""

PROMPT_VERSION = "explain-v2"
MAX_WORDS = 180

# Supported explanation languages: code -> name used in the prompt.
LANGUAGES = {
    "en": "English",
    "si": "Sinhala",
    "ta": "Tamil",
    "id": "Bahasa Indonesia",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ms": "Malay",
    "th": "Thai",
    "tl": "Filipino",
    "zh": "Simplified Chinese",
}

# BCP-47 locales for Gemini TTS, only for languages it is known to speak. Check the
# current TTS language list before adding one; others get text without audio.
TTS_LOCALES = {
    "en": "en-US",
    "ta": "ta-IN",
    "id": "id-ID",
    "vi": "vi-VN",
    "hi": "hi-IN",
    "th": "th-TH",
}

SYSTEM = f"""\
You explain a loan assessment to a small-business owner who may have little formal
education. Write in the requested language, in short sentences, warmly and plainly.

Rules:
- Use only the facts given. Do not invent numbers, reasons or promises.
- Say clearly that a loan officer makes the final decision.
- Explain the main reasons, then what the applicant could do to improve their chances.
- No jargon: say "the money left after expenses", not "net cash flow".
- At most {MAX_WORDS} words.
- Unless the language is English, also give english_text: the same explanation in
  English, sentence for sentence, so a loan officer who cannot read the language can
  check what the borrower is told. Translate faithfully; add nothing.
"""


def borrower_prompt(language: str, facts: str) -> str:
    """`language` must be a key of LANGUAGES; callers validate it first."""
    return f"Language: {LANGUAGES[language]}\n\nFacts:\n{facts}"
