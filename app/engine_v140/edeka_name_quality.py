from __future__ import annotations

import re
import unicodedata

from .product_cleaning import clean_product_name, product_name_issue

_NOISE_WORDS = {
    "aktion", "angebot", "angebote", "klasse", "klassell", "deutschland", "bund",
    "woche", "maerkten", "märkten", "teilnehmenden", "strasse", "straße", "haftung",
    "vorrat", "drokthler", "payback", "markt", "filiale", "internet", "qr", "deko",
    "tiefgefroren", "versch", "sorten", "stueck", "stück", "packung", "beutel",
}
_BAD_FRAGMENTS = (
    "er ein genuss",
    "deutschland ohne deko",
    "teilnehmenden märkten",
    "teilnehmenden maerkten",
    "drokthler haftung",
    "straße 35",
    "strasse 35",
    "der woche",
    "thunfisch 99",
)
_ALLOWED_SHORT = {"bio", "xxl", "rot", "mix", "mini", "pak", "choi"}


def _fold(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", (value or "").lower())
        if not unicodedata.combining(char)
    )


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9äöüß]+", _fold(value))


def strict_name_ok(value: str | None) -> bool:
    name = clean_product_name(value or "").strip(" -,:;.|/")
    if not name or product_name_issue(name) or len(name) < 4 or len(name) > 80:
        return False
    folded = re.sub(r"\s+", " ", _fold(name)).strip()
    if any(fragment in folded for fragment in _BAD_FRAGMENTS):
        return False
    if re.search(r"\b(?:straße|strasse|haftung|vorrat|internet|qr|payback)\b", folded):
        return False
    if re.search(r"\b\d{2,}\b", folded):
        return False
    if any(symbol in name for symbol in ("|", "=", "<", ">", "_")):
        return False

    tokens = _tokens(name)
    alpha = [token for token in tokens if re.search(r"[a-zäöüß]", token)]
    if not alpha:
        return False
    meaningful = [token for token in alpha if token not in _NOISE_WORDS]
    if not meaningful:
        return False

    # OCR fragments such as "Pr", "sta", "ie" at the end are a strong sign
    # that a neighbouring line or a clipped word was used as the title.
    tail = meaningful[-1]
    if len(tail) <= 2 and tail not in _ALLOWED_SHORT:
        return False
    if len(tail) == 3 and tail not in _ALLOWED_SHORT and len(meaningful) > 1:
        return False

    letters = sum(character.isalpha() for character in name)
    if letters / max(len(name), 1) < 0.68:
        return False
    return True


def _token_set(value: str) -> set[str]:
    return {
        token for token in _tokens(value)
        if len(token) >= 3 and token not in _NOISE_WORDS
    }


def _agreement(a: str, b: str) -> float:
    left = _token_set(a)
    right = _token_set(b)
    if not left or not right:
        return 0.0
    overlap = left & right
    return len(overlap) / max(1, min(len(left), len(right)))


def choose_consensus_name(candidates: list[str]) -> str | None:
    """Return a title only when independent OCR passes substantially agree.

    EDEKA image flyers are noisy enough that a plausible-looking single OCR
    title is not sufficient. Requiring agreement between at least two passes
    trades some recall for much higher public name precision.
    """
    clean: list[str] = []
    for candidate in candidates:
        name = clean_product_name(candidate or "").strip(" -,:;.|/")
        if strict_name_ok(name) and name not in clean:
            clean.append(name)
    if not clean:
        return None
    if len(clean) == 1:
        return None

    scored: list[tuple[float, int, str]] = []
    for index, name in enumerate(clean):
        agreements = [
            _agreement(name, other)
            for other_index, other in enumerate(clean)
            if other_index != index
        ]
        best = max(agreements, default=0.0)
        support = sum(value >= 0.6 for value in agreements)
        scored.append((best, support, name))
    best, support, name = max(scored, key=lambda item: (item[1], item[0], len(item[2])))
    if support < 1 or best < 0.6:
        return None
    return name
