from __future__ import annotations


def normalize_gtin(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def valid_gtin(value: str) -> bool:
    code = normalize_gtin(value)
    if len(code) not in {8, 12, 13, 14}:
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check
