"""Unit tests for app.shared.text (no database)."""

import unicodedata

import pytest

from app.shared.text import normalize_display_name, normalize_text

# Built with chr() so the formatter keeps them unambiguous in source.
FULLWIDTH_ABC = "".join(chr(c) for c in (0xFF21, 0xFF22, 0xFF23))  # full-width A B C
IDEOGRAPHIC_SPACE = chr(0x3000)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Chini  ", "chini"),
        ("CHEENI", "cheeni"),
        ("Tata Salt (1kg)", "tata salt 1kg"),
        ("Tata-Salt\t\n 1 kg", "tata salt 1 kg"),
        ("Maggi® Masala™", "maggi masala"),
        # full-width "ABC" + ideographic space (NFKC folds them)
        (FULLWIDTH_ABC + IDEOGRAPHIC_SPACE + "Atta", "abc atta"),
        ("Amul   Gold!!!", "amul gold"),
        ("Straße", "strasse"),  # case-folding, not just lower()
        ("Coca-Cola 500ml", "coca cola 500ml"),
        ("Atta ₹250 🛒", "atta 250"),  # currency symbol and emoji removed
    ],
)
def test_latin_normalisation(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("शक्कर", "शक्कर"),  # virama (conjunct) preserved
        ("चीनी", "चीनी"),  # vowel sign ी preserved
        ("  दूध।  ", "दूध"),  # danda is punctuation
        ("सरसों का तेल", "सरसों का तेल"),  # anusvara/chandrabindu marks preserved
        ("२ किलो आटा", "2 किलो आटा"),  # Devanagari digits -> ASCII
        ("Amul दूध (1 लीटर)", "amul दूध 1 लीटर"),  # mixed script
        ("ਖੰਡ", "ਖੰਡ"),  # Gurmukhi (Punjabi) with tippi preserved
    ],
)
def test_indic_normalisation(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_vowel_signs_are_never_dropped() -> None:
    # "चीनी" (sugar) vs "चनी": dropping the mark would merge different words.
    assert normalize_text("चीनी") != normalize_text("चनी")


def test_composed_and_decomposed_forms_match() -> None:
    composed = "क़"  # क़ (precomposed QA)
    decomposed = "क़"  # क + nukta
    assert normalize_text(composed) == normalize_text(decomposed)
    nfd = unicodedata.normalize("NFD", "सरसों")
    assert normalize_text(nfd) == normalize_text("सरसों")


def test_zero_width_joiners_are_removed() -> None:
    with_zwj = "क्‍ष"
    with_zwnj = "क्‌ष"
    assert normalize_text(with_zwj) == normalize_text(with_zwnj) == "क्ष"


@pytest.mark.parametrize("raw", ["", "   ", "!!!", "(-)", "।।", "‍"])
def test_empty_results(raw: str) -> None:
    assert normalize_text(raw) == ""


def test_leading_combining_mark_is_dropped() -> None:
    assert normalize_text("ा दूध") == "दूध"


@pytest.mark.parametrize(
    "raw", ["Tata Salt (1kg)", "शक्कर", "  Amul दूध।", FULLWIDTH_ABC, "क़", "Straße"]
)
def test_idempotent(raw: str) -> None:
    once = normalize_text(raw)
    assert normalize_text(once) == once


def test_display_name_preserves_meaning() -> None:
    assert normalize_display_name("  Tata   Salt (1kg) ") == "Tata Salt (1kg)"
    assert normalize_display_name("दूध  ") == "दूध"
    assert normalize_display_name(unicodedata.normalize("NFD", "सरसों")) == "सरसों"
