#!/usr/bin/env python3
"""Check that SESSION, submission metadata, and the submit ZIP are ready for LINE Creators Market registration.

Exit 1 with ERROR lines when anything blocks P8. Never submits anything.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zipfile
from pathlib import Path

ALLOWED_COUNTS = {8, 16, 24, 32, 40}
TITLE_RANGE = (2, 40)
DESCRIPTION_RANGE = (10, 160)
CREATOR_MAX = 50
COPYRIGHT_MAX = 50
MAX_TAGS_PER_STAMP = 9
BANNED_PATTERNS = (r"\bline\b", r"発売", r"検索", r"http://", r"https://", r"www\.")
SESSION_REQUIRED = {
    "publish": {"yes"},
    "consent": {"yes"},
    "adult": {"yes"},
    "rights": {"own", "licensed"},
    "validation": {"ok"},
}


def parse_session(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def has_fullwidth(text: str) -> bool:
    return any(unicodedata.east_asian_width(ch) in ("W", "F") for ch in text)


def has_emoji_or_symbol(text: str) -> bool:
    return any(unicodedata.category(ch) == "So" or ord(ch) >= 0x1F000 for ch in text)


def check_text(label: str, text: str, length_range: tuple[int, int], ascii_only: bool, errors: list[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        errors.append(f"{label} is empty")
        return
    low, high = length_range
    if not low <= len(text) <= high:
        errors.append(f"{label} length {len(text)} is outside {low}..{high}")
    if ascii_only and has_fullwidth(text):
        errors.append(f"{label} contains full-width characters")
    if has_emoji_or_symbol(text):
        errors.append(f"{label} contains emoji or symbol characters")
    lowered = text.lower()
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, lowered):
            errors.append(f"{label} contains banned text matching '{pattern}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate check before LINE Creators Market registration (P8)")
    parser.add_argument("--session", required=True)
    parser.add_argument("--submission", required=True)
    parser.add_argument("--zip", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    session_path = Path(args.session)
    if not session_path.exists():
        errors.append(f"missing SESSION {session_path}")
        session: dict[str, str] = {}
    else:
        session = parse_session(session_path)
        for key, allowed in SESSION_REQUIRED.items():
            value = session.get(key, "missing")
            if value not in allowed:
                errors.append(f"SESSION {key}={value}, required one of {sorted(allowed)}")
        if session.get("text_mode") == "ai" and session.get("text_check") != "ok":
            errors.append(f"SESSION text_mode=ai requires text_check=ok (found {session.get('text_check', 'missing')}); run verify_text.py and get visual approval")
        if session.get("source") == "photo" and session.get("character", "pending") in ("pending", ""):
            errors.append("SESSION character name is not fixed; real names must not be used in metadata")

    submission_path = Path(args.submission)
    if not submission_path.exists():
        errors.append(f"missing submission {submission_path}")
        meta: dict = {}
    else:
        try:
            meta = json.loads(submission_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"submission is not valid JSON: {exc}")
            meta = {}

    count = meta.get("count")
    if count not in ALLOWED_COUNTS:
        errors.append(f"submission count {count} is not one of {sorted(ALLOWED_COUNTS)}")
    if session.get("count") and count is not None and str(count) != session["count"]:
        errors.append(f"submission count {count} != SESSION count {session['count']}")

    title = meta.get("title", {})
    description = meta.get("description", {})
    check_text("title.en", title.get("en", ""), TITLE_RANGE, True, errors)
    check_text("title.ja", title.get("ja", ""), TITLE_RANGE, False, errors)
    check_text("description.en", description.get("en", ""), DESCRIPTION_RANGE, True, errors)
    check_text("description.ja", description.get("ja", ""), DESCRIPTION_RANGE, False, errors)

    creator = meta.get("creator_name", "")
    if not creator:
        errors.append("creator_name is empty")
    elif len(creator) > CREATOR_MAX:
        errors.append(f"creator_name length {len(creator)} > {CREATOR_MAX}")

    copyright_text = meta.get("copyright", "")
    if not copyright_text:
        errors.append("copyright is empty")
    elif len(copyright_text) > COPYRIGHT_MAX or not copyright_text.isascii():
        errors.append("copyright must be ASCII and at most 50 characters")

    if meta.get("ai_used") is not True:
        errors.append("ai_used must be true; declare AI use honestly in the registration form")
    if not isinstance(meta.get("price_jpy"), int):
        errors.append("price_jpy must be an integer chosen from the registration form options")
    if meta.get("sales_area") not in ("all", "selected"):
        errors.append("sales_area must be 'all' or 'selected'")
    if not isinstance(meta.get("private"), bool):
        errors.append("private must be true or false")

    tags = meta.get("tags", {})
    if isinstance(tags, dict):
        for key, values in tags.items():
            if isinstance(values, list) and len(values) > MAX_TAGS_PER_STAMP:
                errors.append(f"tags for {key} exceed {MAX_TAGS_PER_STAMP}")
    else:
        warnings.append("tags is not an object; skipping tag check")

    zip_path = Path(args.zip)
    if not zip_path.exists():
        errors.append(f"missing ZIP {zip_path}")
    elif count in ALLOWED_COUNTS:
        if zip_path.stat().st_size > 60_000_000:
            errors.append("ZIP exceeds 60MB")
        with zipfile.ZipFile(zip_path) as archive:
            names = sorted(archive.namelist())
        expected = sorted(["main.png", "tab.png", *[f"stamp{i:02d}.png" for i in range(1, count + 1)]])
        if names != expected:
            errors.append(f"ZIP members differ from expected {count}-stamp pack: found {len(names)} entries")

    print(f"errors={len(errors)} warnings={len(warnings)}")
    for message in errors:
        print("ERROR", message)
    for message in warnings:
        print("WARN", message)
    if errors:
        raise SystemExit(1)
    print("READY: present metadata for P7 approval; the user presses the review request button in P8")


if __name__ == "__main__":
    main()
