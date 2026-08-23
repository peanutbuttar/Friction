import random

import pytest

from friction.challenges import core as C

TARGET = "Call me Ishmael. Some years ago—never mind how long precisely—having"


# --- forgiving marking -----------------------------------------------------

def test_exact_match_passes():
    assert C.mark_transcription(TARGET, TARGET).passed


def test_straight_quotes_and_hyphens_accepted():
    """Nobody types an em dash. Typing -- must be fine."""
    typed = "Call me Ishmael. Some years ago--never mind how long precisely--having"
    assert C.mark_transcription(typed, TARGET).passed


def test_case_insensitive():
    assert C.mark_transcription(TARGET.upper(), TARGET).passed


def test_whitespace_and_linebreaks_collapsed():
    typed = TARGET.replace(" ", "\n  ")
    assert C.mark_transcription(typed, TARGET).passed


def test_small_typo_within_budget_passes():
    typed = TARGET.replace("Ishmael", "Ishmeal")      # 2 transposed chars
    assert C.mark_transcription(typed, TARGET, typo_budget_ratio=0.05).passed


def test_zero_budget_rejects_a_typo():
    typed = TARGET.replace("Ishmael", "Ishmeal")
    assert not C.mark_transcription(typed, TARGET, typo_budget_ratio=0.0).passed


def test_wrong_text_fails():
    assert not C.mark_transcription("I am not typing this", TARGET).passed


def test_empty_fails():
    assert not C.mark_transcription("", TARGET).passed


def test_stopping_halfway_fails():
    assert not C.mark_transcription(TARGET[:len(TARGET) // 2], TARGET).passed


def test_pasting_it_twice_fails():
    assert not C.mark_transcription(TARGET + TARGET, TARGET).passed


def test_marking_reports_useful_numbers():
    m = C.mark_transcription("Call me", TARGET)
    assert m.target_chars == len(C.normalize(TARGET))
    assert 0 < m.progress < 1


# --- edit distance ---------------------------------------------------------

@pytest.mark.parametrize("a,b,d", [
    ("", "", 0), ("abc", "abc", 0), ("abc", "abd", 1),
    ("abc", "ab", 1), ("ab", "abc", 1), ("kitten", "sitting", 3),
])
def test_edit_distance(a, b, d):
    assert C.edit_distance(a, b) == d


def test_real_passage_marking_is_fast():
    """The DP is O(n*m); make sure a real 250-word passage is still instant."""
    import time
    text = C.load_passage("moby_dick")
    t0 = time.time()
    assert C.mark_transcription(text, text).passed
    assert time.time() - t0 < 2.0


# --- passages --------------------------------------------------------------

def test_both_passages_present_and_sized():
    for name in ("moby_dick", "great_gatsby"):
        words = len(C.load_passage(name).split())
        assert 200 <= words <= 500, f"{name} has {words} words, spec says 200-500"


def test_alternate_ping_pongs():
    names = ["moby_dick", "great_gatsby"]
    assert C.pick_passage(names, "moby_dick") == "great_gatsby"
    assert C.pick_passage(names, "great_gatsby") == "moby_dick"


def test_first_time_picks_something_valid():
    assert C.pick_passage(["moby_dick", "great_gatsby"], None) in C.available_passages()


def test_titles_are_human_readable():
    assert C.title_for("moby_dick") == "Moby-Dick"
    assert C.title_for("great_gatsby") == "The Great Gatsby"


# --- arithmetic ------------------------------------------------------------

def test_sum_is_solvable_and_correct():
    rng = random.Random(1)
    for _ in range(200):
        s = C.make_sum(2, ["+", "-", "*"], rng=rng)
        assert eval(s.question) == s.answer      # noqa: S307 - generated, not input
        assert C.mark_sum(str(s.answer), s.answer)


def test_subtraction_never_negative():
    rng = random.Random(7)
    for _ in range(200):
        s = C.make_sum(2, ["-"], rng=rng)
        assert s.answer >= 0


def test_wrong_and_junk_answers_rejected():
    for bad in ["", "  ", "abc", "12.5", None]:
        assert not C.mark_sum(bad, 42)
    assert not C.mark_sum("41", 42)


def test_answer_tolerates_spaces_and_commas():
    assert C.mark_sum("  1,024 ", 1024)
