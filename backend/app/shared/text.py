"""Text normalisation for matching names and aliases (product/customer search, voice later).

``normalize_text`` produces a comparison key; it is never shown to users. Rules:

0. Symbols (®, ™, ₹, emoji) become spaces *before* NFKC, so "™" never turns into "tm".
1. Unicode NFKC: compatibility forms fold (full-width letters, ligatures) and canonically
   equivalent spellings match (composed vs decomposed Devanagari, nukta forms).
2. Case-fold (locale-independent lowercase).
3. Decimal digits of any script map to ASCII (Devanagari "२" -> "2").
4. Letters (L*), combining marks (M*: Devanagari/Gurmukhi vowel signs, virama, nukta,
   anusvara) and digits are kept. Marks are essential: dropping "ी" from "चीनी" would change
   the word.
5. Format characters (ZWJ/ZWNJ, which only affect conjunct rendering) are removed.
6. Punctuation, symbols and separators become a single space; whitespace is collapsed and
   trimmed (so "Tata-Salt (1kg)" -> "tata salt 1kg").

No transliteration between scripts happens here ("chini" and "चीनी" stay different keys);
phonetic/transliteration keys are a later (voice) concern.
"""

import unicodedata

_KEEP_CATEGORIES = ("L", "M")


def normalize_text(value: str) -> str:
    """Return the normalised comparison key for ``value`` (may be empty)."""
    # Symbols first (before NFKC): otherwise "™" would decompose into the letters "TM".
    value = "".join(" " if unicodedata.category(ch)[0] == "S" else ch for ch in value)
    text = unicodedata.normalize("NFKC", value).casefold()
    out: list[str] = []
    pending_space = False
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Nd":
            piece = str(unicodedata.decimal(ch))
        elif category[0] in _KEEP_CATEGORIES or category in ("Nl", "No"):
            piece = ch
        elif category == "Cf":
            continue  # zero-width joiners etc.: invisible, never separate words
        else:
            pending_space = True  # punctuation, symbols, whitespace, controls
            continue
        if pending_space and out:
            out.append(" ")
        pending_space = False
        out.append(piece)
    # A combining mark must not start a word (it would attach to nothing).
    result = "".join(out)
    while result and unicodedata.category(result[0])[0] == "M":
        result = result[1:].lstrip()
    return result


def normalize_display_name(value: str) -> str:
    """Tidy a user-entered display name without changing its meaning: NFC, trim, collapse
    internal whitespace. Case and punctuation are preserved."""
    return " ".join(unicodedata.normalize("NFC", value).split())
