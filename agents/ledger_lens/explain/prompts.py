"""Prompts for borrower explanations. Only structured, already-checked facts go in:
never raw text from uploaded documents, which could carry injected instructions."""

PROMPT_VERSION = "explain-v1"

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

SYSTEM = """\
You explain a loan assessment to a small-business owner who may have little formal
education. Write in the requested language, in short sentences, warmly and plainly.

Rules:
- Use only the facts given. Do not invent numbers, reasons or promises.
- Say clearly that a loan officer makes the final decision.
- Explain the main reasons, then what the applicant could do to improve their chances.
- No jargon: say "the money left after expenses", not "net cash flow".
- At most 180 words.
"""


def borrower_prompt(language: str, facts: str) -> str:
    return f"Language: {LANGUAGES.get(language, language)}\n\nFacts:\n{facts}"
