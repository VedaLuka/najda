"""Quantity parsing helpers: Arabic-Indic digits and number words in Arabic / English."""
from __future__ import annotations

import re

ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "واحد": 1, "وحده": 1, "اثنين": 2, "ثنتين": 2, "اثنان": 2, "ثلاث": 3, "ثلاثة": 3, "ثلاثه": 3,
    "اربع": 4, "أربع": 4, "اربعة": 4, "خمس": 5, "خمسة": 5, "خمسه": 5,
}


def normalize_digits(text: str) -> str:
    return text.translate(ARABIC_INDIC)


def to_ascii_digits(text: str) -> str:
    return normalize_digits(text)


def parse_quantity(fragment: str) -> int | None:
    """Quantity mentioned in a short text fragment, or None if no number is present."""
    m = re.search(r"[0-9]+", fragment)  # ASCII only: Arabic-Indic digits need normalize_digits()
    if m:
        return int(m.group())
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"(^|\s){re.escape(word)}(\s|$)", fragment):
            return n
    return None
