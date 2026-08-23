"""Challenge rules: generating them and marking them. No UI, no I/O.

Separate from the windows so the marking can be tested directly. Getting this
wrong in either direction is bad: too strict and a stray autocorrect forces you
to retype 250 words, which is enraging rather than frictional; too loose and the
challenge stops being a real cost.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PASSAGE_DIR = Path(__file__).resolve().parent.parent / "passages"

# Gutenberg texts use typographic punctuation. Typing a straight quote or a
# double hyphen must count as correct -- the challenge tests that you sat and
# typed it, not that you can reproduce typography.
PUNCT_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "―": "-", "−": "-",
    "…": "...", " ": " ",
}


# --- transcription ---------------------------------------------------------

def normalize(text: str, *, case: bool = True, whitespace: bool = True,
              punctuation: bool = True) -> str:
    text = unicodedata.normalize("NFC", text)
    if punctuation:
        for src, dst in PUNCT_MAP.items():
            text = text.replace(src, dst)
        # An em dash normalizes to "-", but people type "--" for one. Collapse
        # runs of hyphens so both spellings land on the same thing.
        text = re.sub(r"-{2,}", "-", text)
    if case:
        text = text.lower()
    if whitespace:
        text = re.sub(r"\s+", " ", text).strip()
    return text


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance, two-row DP so memory stays O(min(len))."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1,        # deletion
                               current[j - 1] + 1,     # insertion
                               previous[j - 1] + (ca != cb)))  # substitution
        previous = current
    return previous[-1]


@dataclass
class Marking:
    passed: bool
    distance: int
    allowed: int
    typed_chars: int
    target_chars: int

    @property
    def progress(self) -> float:
        return min(1.0, self.typed_chars / self.target_chars) if self.target_chars else 0.0


def mark_transcription(typed: str, target: str, *, typo_budget_ratio: float = 0.02,
                       case: bool = True, whitespace: bool = True,
                       punctuation: bool = True) -> Marking:
    t = normalize(typed, case=case, whitespace=whitespace, punctuation=punctuation)
    g = normalize(target, case=case, whitespace=whitespace, punctuation=punctuation)
    allowed = int(len(g) * typo_budget_ratio)
    # Short-circuit: if the lengths are wildly off it cannot pass, and the DP
    # over ~1500 characters is not worth running.
    if abs(len(t) - len(g)) > allowed:
        return Marking(False, abs(len(t) - len(g)), allowed, len(t), len(g))
    d = edit_distance(t, g)
    return Marking(d <= allowed, d, allowed, len(t), len(g))


def correct_prefix_len(typed: str, target: str) -> int:
    """How far the typing matches from the start. For live feedback only."""
    n = 0
    for a, b in zip(typed, target):
        if a != b:
            break
        n += 1
    return n


# --- passages --------------------------------------------------------------

def available_passages() -> list[str]:
    return sorted(p.stem for p in PASSAGE_DIR.glob("*.txt"))


def load_passage(name: str) -> str:
    path = PASSAGE_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"no passage named {name!r} in {PASSAGE_DIR}")
    return path.read_text(encoding="utf-8").strip()


def pick_passage(names: list[str], last: str | None, rotate: str = "alternate") -> str:
    """Which passage comes next.

    'alternate' strictly ping-pongs, so you never get the same one twice running
    and can't settle into muscle memory on one text.
    """
    names = [n for n in names if n in available_passages()] or available_passages()
    if not names:
        raise FileNotFoundError("no passages installed")
    if rotate == "random" or last not in names:
        return random.choice(names) if rotate == "random" else names[0]
    return names[(names.index(last) + 1) % len(names)]


def title_for(name: str) -> str:
    return {"moby_dick": "Moby-Dick", "great_gatsby": "The Great Gatsby"} \
        .get(name, name.replace("_", " ").title())


# --- arithmetic ------------------------------------------------------------

@dataclass
class Sum:
    question: str
    answer: int


def make_sum(digits: int = 2, operations: list[str] | None = None,
             rng: random.Random | None = None) -> Sum:
    rng = rng or random
    ops = operations or ["+", "-", "*"]
    op = rng.choice(ops)
    lo, hi = 10 ** (digits - 1), 10 ** digits - 1
    a, b = rng.randint(lo, hi), rng.randint(lo, hi)
    if op == "-" and b > a:
        a, b = b, a                       # keep it non-negative; no easier, less fiddly
    answer = {"+": a + b, "-": a - b, "*": a * b}[op]
    return Sum(question=f"{a} {op} {b}", answer=answer)


def mark_sum(given: str, answer: int) -> bool:
    try:
        return int(given.strip().replace(",", "")) == answer
    except (ValueError, AttributeError):
        return False
