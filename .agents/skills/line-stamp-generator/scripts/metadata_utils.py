"""Strict JSON helpers shared by project migration and publish validation."""
from __future__ import annotations

import json
import math


class DuplicateKeyError(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    """Reject JavaScript numeric constants that RFC 8259 JSON does not allow."""
    raise json.JSONDecodeError(f"non-finite JSON number {value!r} is not allowed", value, 0)


def _parse_finite_float(value: str) -> float:
    """Reject valid-looking exponents that overflow Python's float to infinity."""
    result = float(value)
    if not math.isfinite(result):
        raise json.JSONDecodeError(f"JSON number {value!r} exceeds the finite range", value, 0)
    return result


def loads_no_duplicates(text: str):
    """Parse RFC 8259 JSON, rejecting duplicate keys at every object depth."""
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_non_finite_number,
        parse_float=_parse_finite_float,
    )
