"""Name screening against sanctions lists.

Matching is deliberately generous (names are transliterated many ways across JAPAC
scripts), so a hit means "a person should check", never "reject".
"""

import json
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel

MATCH_THRESHOLD = 0.88
TOKEN_THRESHOLD = 0.85


class ListedName(BaseModel):
    name: str
    list: str
    reference: str


class ScreeningHit(BaseModel):
    screened_name: str
    listed: ListedName
    similarity: float


def normalise(name: str) -> str:
    """Lowercase, strip accents and punctuation, and sort tokens so word order is ignored."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = "".join(ch if ch.isalnum() else " " for ch in ascii_name.lower()).split()
    return " ".join(sorted(tokens))


class SanctionsScreen:
    def __init__(self, list_path: Path) -> None:
        data = json.loads(list_path.read_text(encoding="utf-8"))
        self._entries = [ListedName.model_validate(e) for e in data["entries"]]
        self._normalised = [(normalise(e.name), e) for e in self._entries]

    def screen(self, names: list[str]) -> list[ScreeningHit]:
        hits = []
        for name in filter(None, names):
            target = normalise(name)
            for listed_norm, entry in self._normalised:
                similarity = max(
                    SequenceMatcher(None, target, listed_norm).ratio(),
                    token_overlap(target, listed_norm),
                )
                if similarity >= MATCH_THRESHOLD:
                    hit = ScreeningHit(
                        screened_name=name, listed=entry, similarity=round(similarity, 3)
                    )
                    hits.append(hit)
        return hits


def token_overlap(a: str, b: str) -> float:
    """Share of the shorter name's words found (fuzzily) in the longer name.

    Catches dropped or added middle names ("Tran Hung" vs "Tran Van Hung"). Single-word
    names are excluded: one shared word is far too weak a signal on its own.
    """
    short, long = sorted((a.split(), b.split()), key=len)
    if len(short) < 2:
        return 0.0
    found = sum(
        any(SequenceMatcher(None, word, other).ratio() >= TOKEN_THRESHOLD for other in long)
        for word in short
    )
    return found / len(short)
