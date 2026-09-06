#!/usr/bin/env python3
"""Check candidate P7 metadata and its project artifacts before user approval.

Exit 1 with ERROR lines when anything blocks P7 approval. Never submits anything.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from metadata_utils import DuplicateKeyError, loads_no_duplicates
from project_context import enforce_facade_project
from session_contract import (
    require_complete_text_evidence,
    require_three_view_evidence,
    require_review_evidence,
)
from validate_pack import (
    validate_png,
    validate_submission_names,
    validate_stamp_sources,
    validate_zip,
)

ALLOWED_COUNTS = {8, 16, 24, 32, 40}
TITLE_RANGE = (2, 40)
DESCRIPTION_RANGE = (10, 160)
CREATOR_MAX = 50
COPYRIGHT_MAX = 50
MAX_TAGS_PER_STAMP = 9
SESSION_SCHEMA_VERSION = "5"
SUBMISSION_SCHEMA_VERSION = 3
PROJECT_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
WINDOWS_RESERVED_NAMES = {
    "ACTIVE",
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
PROVENANCE_SCOPES = {"character-design", "stamp-images", "text", "other"}
PROVENANCE_GATES = {"P1", "P2", "P4", "P5"}
PROVENANCE_REQUIRED_FIELDS = {
    "ai_used",
    "scope",
    "tool_and_model",
    "generated_at",
    "prompt_reference",
    "reviewed_by_user_at_gate",
}
PROVENANCE_PLACEHOLDER_RE = re.compile(r"<[^>\r\n]+>")
# Normalize before matching so case and full-width ASCII cannot bypass these checks.
# ASCII-only lookarounds still allow matches next to Japanese text while avoiding
# false positives such as "baseline".
BANNED_TEXT_PATTERNS = (
    ("LINE", re.compile(r"(?<![a-z])line(?![a-z])")),
    ("発売", re.compile(r"発売")),
    ("検索", re.compile(r"検索")),
)
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s]+"
    r"|(?<![a-z0-9_@])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})(?::[0-9]{1,5})?(?:[/#?][^\s]*)?"
    r"|(?<![a-z0-9_@])(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
    r"(?::[0-9]{1,5})?(?:[/#?][^\s]*)?"
)
SESSION_REQUIRED = {
    "materials": {"received"},
    "gate": {"P7"},
    "publish": {"yes"},
    "validation": {"ok"},
    "submission": {"not-started"},
}
ALLOWED_SOURCES = {"photo", "character"}
DEPRECATED_SESSION_KEYS = {"adult", "consent", "rights"}


def parse_session(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse the flat SESSION fields and reject ambiguous duplicate keys."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if match:
            key, value = match.groups()
            if key in values:
                errors.append(f"SESSION key {key!r} is duplicated (line {line_number})")
            else:
                values[key] = value.strip()
    return values, errors


def check_project_layout(
    session_path: Path,
    submission_path: Path,
    zip_path: Path,
    errors: list[str],
) -> Path:
    """Bind all P7 inputs to the selected project and reject symlink indirection."""
    project_dir = session_path.parent
    try:
        enforce_facade_project(project_dir, "publish-readiness")
    except ValueError as exc:
        errors.append(str(exc))
    projects_dir = project_dir.parent
    if session_path.name != "SESSION.md" or projects_dir.name != "projects":
        errors.append("--session must be projects/<slug>/SESSION.md")
    for label, path in (
        ("project directory", project_dir),
        ("projects directory", projects_dir),
        ("SESSION", session_path),
        ("submission directory", submission_path.parent),
        ("submission", submission_path),
        ("submit directory", zip_path.parent),
        ("ZIP", zip_path),
    ):
        if path.is_symlink():
            errors.append(f"{label} must not be a symlink: {path}")

    try:
        resolved_project = project_dir.resolve()
        expected_submission = (resolved_project / "meta" / "submission.json").resolve()
        expected_submit_dir = (resolved_project / "submit").resolve()
        resolved_submission = submission_path.resolve()
        resolved_zip = zip_path.resolve()
    except OSError as exc:
        errors.append(f"cannot resolve P7 project paths: {exc}")
        return project_dir

    if resolved_submission != expected_submission:
        errors.append("--submission must be the active project's meta/submission.json")
    if resolved_zip.parent != expected_submit_dir or zip_path.suffix.casefold() != ".zip":
        errors.append("--zip must be a .zip file directly inside the active project's submit/")

    active_path = projects_dir / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        errors.append("projects/ACTIVE must be a regular non-symlink file for P7")
    else:
        try:
            active = active_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read projects/ACTIVE as UTF-8: {exc}")
        else:
            if active != project_dir.name:
                errors.append(
                    f"projects/ACTIVE={active!r} does not select SESSION project {project_dir.name!r}"
                )
    return project_dir


def has_fullwidth(text: str) -> bool:
    return any(unicodedata.east_asian_width(ch) in ("W", "F") for ch in text)


def has_emoji_or_symbol(text: str) -> bool:
    """Reject symbols and emoji controls without rejecting supplementary CJK letters."""
    for character in text:
        codepoint = ord(character)
        if unicodedata.category(character) == "So":
            return True
        if 0x1F3FB <= codepoint <= 0x1F3FF:  # emoji skin-tone modifiers (category Sk)
            return True
        if codepoint in {0x200D, 0x20E3, 0xFE0F}:  # ZWJ, keycap mark, emoji variation selector
            return True
    return False


def counted_length(text: str) -> int:
    """Count full-width characters as two, matching Creators Market limits."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def invisible_or_control_characters(text: str) -> list[str]:
    """Return code points unsafe in single-line Creators Market metadata."""
    return [character for character in text if unicodedata.category(character).startswith("C")]


def check_text(label: str, text: str, length_range: tuple[int, int], ascii_only: bool, errors: list[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        errors.append(f"{label} is empty")
        return
    low, high = length_range
    length = counted_length(text)
    if not low <= length <= high:
        errors.append(f"{label} counted length {length} is outside {low}..{high}")
    if ascii_only and has_fullwidth(text):
        errors.append(f"{label} contains full-width characters")
    if has_emoji_or_symbol(text):
        errors.append(f"{label} contains emoji or symbol characters")
    unsafe_characters = invisible_or_control_characters(text)
    if unsafe_characters:
        codepoints = sorted({f"U+{ord(character):04X}" for character in unsafe_characters})
        errors.append(f"{label} contains invisible or control characters: {codepoints}")
    visible_text = "".join(
        character for character in text if not unicodedata.category(character).startswith("C")
    )
    normalized = unicodedata.normalize("NFKC", visible_text).casefold()
    for name, pattern in BANNED_TEXT_PATTERNS:
        if pattern.search(normalized):
            errors.append(f"{label} contains banned text {name!r}")
    if URL_PATTERN.search(normalized):
        errors.append(f"{label} contains a URL")


def check_copyright(value: object, errors: list[str]) -> None:
    """Validate the stricter ASCII copyright field, including common banned terms."""
    if not isinstance(value, str) or not value:
        errors.append("copyright is empty")
        return
    if len(value) > COPYRIGHT_MAX or re.fullmatch(r"[A-Za-z0-9]+", value) is None:
        errors.append("copyright must contain only ASCII letters and digits and be at most 50 characters")
        return
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if any(pattern.search(normalized) for _, pattern in BANNED_TEXT_PATTERNS):
        errors.append("copyright contains text prohibited by the LINE metadata rules")


def check_boolean(meta: dict, key: str, errors: list[str]) -> bool | None:
    """Require a real JSON boolean (integers must not pass as booleans)."""
    value = meta.get(key)
    if type(value) is not bool:
        errors.append(f"{key} must be a boolean")
        return None
    return value


def check_sales_area(meta: dict, errors: list[str]) -> None:
    area = meta.get("sales_area")
    countries = meta.get("sales_countries")
    if not isinstance(area, str) or area not in {"all", "some", "selected"}:
        errors.append("sales_area must be 'all', 'some', or 'selected'")
    if not isinstance(countries, list):
        errors.append("sales_countries must be a list")
        return
    invalid = [code for code in countries if not isinstance(code, str) or re.fullmatch(r"[A-Z]{2}", code) is None]
    if invalid:
        errors.append("sales_countries entries must be uppercase ISO-like alpha-2 codes")
    string_codes = [code for code in countries if isinstance(code, str)]
    if len(string_codes) != len(set(string_codes)):
        errors.append("sales_countries must not contain duplicates")
    if area == "all" and countries:
        errors.append("sales_area='all' requires an empty sales_countries list")
    elif (area == "some" or area == "selected") and not countries:
        errors.append(f"sales_area={area!r} requires a nonempty sales_countries list")


def check_store_visibility(meta: dict, errors: list[str]) -> None:
    """Require the canonical field and reject every residual legacy alias."""
    if "private" in meta:
        errors.append(
            "private is deprecated and must be removed with public command "
            "`project --root . migrate` before P7 validation"
        )
    if meta.get("store_visibility") not in ("public", "private") and "private" not in meta:
        errors.append("store_visibility must be 'public' or 'private'")


def check_ai_declaration(
    session: dict[str, str], ai_used: bool | None, errors: list[str]
) -> None:
    """Reject declarations contradicted by AI-rendered text recorded in SESSION."""
    if session.get("text_mode") == "ai" and ai_used is not True:
        errors.append("SESSION text_mode=ai requires submission ai_used=true")


def check_project_reference(project_dir: Path, reference: str, label: str, errors: list[str]) -> None:
    """Accept an HTTPS URL or an existing non-symlink file inside this project."""
    if re.fullmatch(r"https://[^\s]+", reference):
        return
    relative = Path(reference)
    if relative.is_absolute():
        errors.append(f"{label} local path must be relative to the active project")
        return
    candidate = project_dir / relative
    if candidate.is_symlink():
        errors.append(f"{label} local path must not be a symlink")
        return
    try:
        resolved_project = project_dir.resolve()
        resolved = candidate.resolve()
    except OSError as exc:
        errors.append(f"cannot resolve {label}: {exc}")
        return
    if not resolved.is_relative_to(resolved_project):
        errors.append(f"{label} local path escapes the active project")
    elif not resolved.is_file():
        errors.append(f"{label} must be an HTTPS URL or an existing project-local file")
    else:
        try:
            if resolved.stat().st_size <= 0:
                errors.append(f"{label} project-local file must not be empty")
                return
            with resolved.open("rb") as handle:
                if not handle.read(1):
                    errors.append(f"{label} project-local file must be readable and non-empty")
        except OSError as exc:
            errors.append(f"cannot read {label} project-local file: {exc}")


def check_ai_provenance(
    project_dir: Path,
    ai_used: bool | None,
    errors: list[str],
    required_scopes: set[str] | None = None,
) -> None:
    if ai_used is not True:
        return
    provenance = project_dir / "meta" / "ai-provenance.md"
    if provenance.is_symlink():
        errors.append("ai_used=true requires a non-symlink meta/ai-provenance.md")
        return
    try:
        resolved_project = project_dir.resolve()
        resolved = provenance.resolve()
    except OSError as exc:
        errors.append(f"cannot resolve meta/ai-provenance.md: {exc}")
        return
    if not resolved.is_relative_to(resolved_project) or not resolved.is_file():
        errors.append("ai_used=true requires project-local meta/ai-provenance.md")
    else:
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read meta/ai-provenance.md as UTF-8: {exc}")
        else:
            if not content.strip():
                errors.append("meta/ai-provenance.md must not be empty")
                return

            fields: dict[str, str] = {}
            for line_number, line in enumerate(content.splitlines(), start=1):
                match = re.match(r"^\s*-\s*([a-z_]+)\s*:\s*(.*?)\s*$", line)
                if not match:
                    continue
                key, value = match.groups()
                if key in fields:
                    errors.append(
                        f"meta/ai-provenance.md field {key!r} is duplicated (line {line_number})"
                    )
                else:
                    fields[key] = value

            for key in sorted(PROVENANCE_REQUIRED_FIELDS - fields.keys()):
                errors.append(f"meta/ai-provenance.md is missing required field {key!r}")
            for key in sorted(PROVENANCE_REQUIRED_FIELDS & fields.keys()):
                value = fields[key].strip()
                if not value or PROVENANCE_PLACEHOLDER_RE.search(value):
                    errors.append(
                        f"meta/ai-provenance.md field {key!r} is empty or still contains a template placeholder"
                    )

            if fields.get("ai_used", "").strip().casefold() != "true":
                errors.append("meta/ai-provenance.md ai_used must be true")

            scope_value = fields.get("scope", "")
            scopes = [part.strip() for part in scope_value.split(",") if part.strip()]
            if not scopes or any(scope not in PROVENANCE_SCOPES for scope in scopes):
                errors.append(
                    "meta/ai-provenance.md scope must be a comma-separated selection from "
                    f"{sorted(PROVENANCE_SCOPES)}"
                )
            elif len(scopes) != len(set(scopes)):
                errors.append("meta/ai-provenance.md scope must not contain duplicates")
            elif required_scopes:
                missing_scopes = sorted(required_scopes - set(scopes))
                if missing_scopes:
                    errors.append(
                        "meta/ai-provenance.md scope is missing required SESSION-derived values: "
                        f"{missing_scopes}"
                    )

            generated_at = fields.get("generated_at", "").strip()
            try:
                generated_date = date.fromisoformat(generated_at)
            except ValueError:
                errors.append("meta/ai-provenance.md generated_at must be an ISO date (YYYY-MM-DD)")
            else:
                if generated_date > date.today():
                    errors.append("meta/ai-provenance.md generated_at must not be in the future")

            reviewed = [
                part for part in re.split(r"\s*[,/]\s*", fields.get("reviewed_by_user_at_gate", "")) if part
            ]
            if not reviewed or any(gate not in PROVENANCE_GATES for gate in reviewed):
                errors.append(
                    "meta/ai-provenance.md reviewed_by_user_at_gate must contain only "
                    f"{sorted(PROVENANCE_GATES)}"
                )

            prompt_reference = fields.get("prompt_reference", "").strip()
            if prompt_reference.casefold() == "inline below":
                note_matches = list(
                    re.finditer(
                        r"^##[ \t]+Prompt or reproducibility note[ \t]*\r?\n"
                        r"(?P<body>.*?)(?=^#{1,6}[ \t]+|\Z)",
                        content,
                        flags=re.MULTILINE | re.DOTALL,
                    )
                )
                if len(note_matches) != 1:
                    errors.append(
                        "meta/ai-provenance.md inline prompt_reference requires exactly one "
                        "Prompt or reproducibility note section"
                    )
                    note_body = ""
                else:
                    note_body = note_matches[0].group("body")
                    field_bullets_after_heading = [
                        match.group(1)
                        for match in re.finditer(
                            r"^\s*-\s*([a-z_]+)\s*:", note_body, flags=re.MULTILINE
                        )
                        if match.group(1) in PROVENANCE_REQUIRED_FIELDS
                    ]
                    if field_bullets_after_heading:
                        errors.append(
                            "meta/ai-provenance.md metadata fields must appear before the prompt note heading"
                        )
                note_lines = [
                    line
                    for line in note_body.splitlines()
                    if not re.match(r"^\s*-\s*[a-z_]+\s*:", line)
                ]
                note = "\n".join(note_lines).strip()
                template_note = (
                    "承認済みのプロンプト、または対象プロジェクト内に保存したプロンプトファイルの一覧を記録する。"
                    "認証情報、実名など申請に不要な個人情報、他プロジェクトへの参照は書かない。"
                )
                if not note or "".join(note.split()) == template_note:
                    errors.append(
                        "meta/ai-provenance.md inline prompt_reference requires a concrete prompt or reproducibility note"
                    )
            elif prompt_reference and not PROVENANCE_PLACEHOLDER_RE.search(prompt_reference):
                relative = Path(prompt_reference)
                if relative.is_absolute():
                    errors.append("meta/ai-provenance.md prompt_reference must be project-relative")
                else:
                    candidate = project_dir / relative
                    if candidate.is_symlink():
                        errors.append("meta/ai-provenance.md prompt_reference must not be a symlink")
                    else:
                        try:
                            resolved_prompt = candidate.resolve()
                        except OSError as exc:
                            errors.append(f"cannot resolve ai prompt_reference: {exc}")
                        else:
                            if resolved_prompt == resolved:
                                errors.append(
                                    "meta/ai-provenance.md prompt_reference must not refer to "
                                    "ai-provenance.md itself"
                                )
                            elif not resolved_prompt.is_relative_to(resolved_project) or not resolved_prompt.is_file():
                                errors.append(
                                    "meta/ai-provenance.md prompt_reference must name an existing project-local file"
                                )
                            else:
                                try:
                                    prompt_content = resolved_prompt.read_text(encoding="utf-8")
                                except (OSError, UnicodeError) as exc:
                                    errors.append(
                                        f"cannot read ai prompt_reference as UTF-8: {exc}"
                                    )
                                else:
                                    if not prompt_content.strip():
                                        errors.append("ai prompt_reference file must not be empty")


def check_session_state(
    session: dict[str, str], session_path: Path, errors: list[str]
) -> None:
    """Require a complete P7 state instead of accepting a few isolated flags."""
    if session.get("schema_version") != SESSION_SCHEMA_VERSION:
        errors.append(
            "SESSION schema_version must be 5; inspect the active project with public command "
            "`project --root . migrate`"
        )
    deprecated = sorted(DEPRECATED_SESSION_KEYS.intersection(session))
    if deprecated:
        errors.append(
            f"SESSION contains deprecated fields {deprecated}; run project migrate first"
        )
    for key, allowed in SESSION_REQUIRED.items():
        value = session.get(key, "missing")
        if value not in allowed:
            errors.append(f"SESSION {key}={value}, required one of {sorted(allowed)}")

    project = session.get("project", "")
    if PROJECT_SLUG_RE.fullmatch(project) is None or project.upper() in WINDOWS_RESERVED_NAMES:
        errors.append("SESSION project must be a portable 2-40 character slug")
    elif project != session_path.parent.name:
        errors.append(
            f"SESSION project={project!r} does not match its directory {session_path.parent.name!r}"
        )

    source = session.get("source", "missing")
    if source not in ALLOWED_SOURCES:
        errors.append(f"SESSION source={source}, required one of {sorted(ALLOWED_SOURCES)}")

    count = session.get("count", "")
    if count not in {str(value) for value in ALLOWED_COUNTS}:
        errors.append(f"SESSION count={count or 'missing'}, required one of {sorted(ALLOWED_COUNTS)}")
    review_version = session.get("review_version", "")
    if re.fullmatch(r"[1-9][0-9]{0,8}", review_version) is None:
        errors.append("SESSION review_version must be a positive version approved at P5")
    design_version = session.get("design_version", "")
    three_view_version = session.get("three_view_version", "")
    if re.fullmatch(r"[1-9][0-9]{0,8}", design_version) is None:
        errors.append("SESSION design_version must be a positive approved P1 version")
    elif session.get("design_evidence") != f"refs/design-v{int(design_version):02d}.json":
        errors.append("SESSION design_evidence must match design_version")
    if session.get("three_view") != "approved" or re.fullmatch(
        r"[1-9][0-9]{0,8}", three_view_version
    ) is None:
        errors.append("SESSION three_view must have a positive approved P2 version")

    text = session.get("text", "missing")
    text_mode = session.get("text_mode", "missing")
    if text_mode == "font":
        errors.append("text_mode=font is no longer supported; preserve this project and create a new ai project for regeneration and normal gate approvals")
    if (text, text_mode) not in {("yes", "ai"), ("no", "none")}:
        errors.append(
            "SESSION text/text_mode must be yes/ai or no/none "
            f"(found {text}/{text_mode})"
        )
    text_check = session.get("text_check", "missing")
    if text_mode == "ai" and text_check != "ok":
        errors.append(
            f"SESSION text_mode=ai requires text_check=ok (found {text_check}); "
            "run public command verify-text and get visual approval"
        )
    elif text_mode != "ai" and text_check != "n/a":
        errors.append(f"SESSION text_mode={text_mode} requires text_check=n/a (found {text_check})")

    character = session.get("character", "").strip()
    if not character or character == "pending" or any(char in character for char in "\r\n"):
        errors.append("SESSION character name is not fixed")


def check_license_proof(
    meta: dict,
    project_dir: Path,
    errors: list[str],
) -> None:
    """Validate optional supporting evidence without making it a publication gate."""
    proof = meta.get("license_proof")
    if proof is None:
        return
    if not isinstance(proof, dict):
        errors.append("license_proof must be an object with status and reference strings")
        return

    status = proof.get("status")
    reference = proof.get("reference")
    if not isinstance(status, str) or status not in {"not-required", "user-confirmed"}:
        errors.append("license_proof.status must be 'not-required' or 'user-confirmed'")
    if not isinstance(reference, str):
        errors.append("license_proof.reference must be a string")
        reference = ""

    if status == "user-confirmed" and not reference.strip():
        errors.append("license_proof.status='user-confirmed' requires a nonempty reference")
    elif status == "not-required" and reference.strip():
        errors.append("license_proof.status='not-required' requires an empty reference")
    if status == "user-confirmed" and reference.strip():
        check_project_reference(project_dir, reference.strip(), "license_proof.reference", errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate candidate metadata before P7 approval")
    parser.add_argument("--session", required=True)
    parser.add_argument("--submission", required=True)
    parser.add_argument("--zip", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    session_path = Path(args.session)
    submission_path = Path(args.submission)
    zip_path = Path(args.zip)
    project_dir = check_project_layout(session_path, submission_path, zip_path, errors)
    if errors:
        print(f"errors={len(errors)} warnings=0")
        for message in errors:
            print("ERROR", message)
        raise SystemExit(1)

    if session_path.is_symlink() or not session_path.is_file():
        errors.append(f"missing SESSION {session_path}")
        session: dict[str, str] = {}
    else:
        try:
            session, session_errors = parse_session(session_path)
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read SESSION as UTF-8: {exc}")
            session = {}
        else:
            errors.extend(session_errors)
            check_session_state(session, session_path, errors)
            try:
                require_three_view_evidence(project_dir, session)
            except ValueError as exc:
                errors.append(f"P7 design evidence: {exc}")
            evidence_count_value = session.get("count", "")
            review_version_value = session.get("review_version", "")
            if evidence_count_value in {str(value) for value in ALLOWED_COUNTS}:
                evidence_count = int(evidence_count_value)
                if re.fullmatch(r"[1-9][0-9]{0,8}", review_version_value):
                    try:
                        require_review_evidence(
                            project_dir, evidence_count, int(review_version_value)
                        )
                    except ValueError as exc:
                        errors.append(f"P7 review evidence: {exc}")
                if session.get("text_mode") == "ai":
                    try:
                        mask_value = session.get("text_mask_version", "")
                        if re.fullmatch(r"[1-9][0-9]{0,8}", mask_value) is None:
                            raise ValueError(
                                "SESSION text_mask_version must be positive for AI text"
                            )
                        require_complete_text_evidence(
                            project_dir, evidence_count, int(mask_value)
                        )
                    except ValueError as exc:
                        errors.append(f"P7 AI text evidence: {exc}")

    if submission_path.is_symlink() or not submission_path.is_file():
        errors.append(f"missing submission {submission_path}")
        meta: dict = {}
    else:
        try:
            meta = loads_no_duplicates(submission_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
            errors.append(f"submission is not valid JSON: {exc}")
            meta = {}
        if not isinstance(meta, dict):
            errors.append("submission JSON root must be an object")
            meta = {}

    if type(meta.get("schema_version")) is not int or meta.get("schema_version") != SUBMISSION_SCHEMA_VERSION:
        errors.append(
            "submission schema_version must be 3; inspect the active project with public command "
            "`project --root . migrate`"
        )

    count = meta.get("count")
    if type(count) is not int or count not in ALLOWED_COUNTS:
        errors.append(f"submission count {count} is not one of {sorted(ALLOWED_COUNTS)}")
    session_count = session.get("count")
    if session_count is not None and count is not None and str(count) != session_count:
        errors.append(f"submission count {count} != SESSION count {session_count}")

    title = meta.get("title", {})
    description = meta.get("description", {})
    if not isinstance(title, dict):
        errors.append("title must be an object with en and ja strings")
        title = {}
    if not isinstance(description, dict):
        errors.append("description must be an object with en and ja strings")
        description = {}
    check_text("title.en", title.get("en", ""), TITLE_RANGE, True, errors)
    check_text("title.ja", title.get("ja", ""), TITLE_RANGE, False, errors)
    check_text("description.en", description.get("en", ""), DESCRIPTION_RANGE, True, errors)
    check_text("description.ja", description.get("ja", ""), DESCRIPTION_RANGE, False, errors)

    creator = meta.get("creator_name", "")
    check_text("creator_name", creator, (1, CREATOR_MAX), False, errors)

    check_copyright(meta.get("copyright", ""), errors)

    ai_used = check_boolean(meta, "ai_used", errors)
    photo_used = check_boolean(meta, "photo_used", errors)
    check_boolean(meta, "premium_participation", errors)
    if photo_used is False and session.get("source") == "photo":
        warnings.append(
            "photo_used=false for a photo-derived project; confirm against the current registration form "
            "that the final redrawn artwork is not declared as photo use"
        )
    check_ai_declaration(session, ai_used, errors)
    required_ai_scopes = {"text"} if session.get("text_mode") == "ai" else set()
    check_ai_provenance(project_dir, ai_used, errors, required_ai_scopes)
    check_license_proof(meta, project_dir, errors)
    price_jpy = meta.get("price_jpy")
    if type(price_jpy) is not int or price_jpy <= 0:
        errors.append("price_jpy must be a positive integer chosen from the current registration form")
    if meta.get("price_confirmed") is not True:
        errors.append(
            "price_confirmed must be true after the user selects price_jpy from the current registration form"
        )
    check_sales_area(meta, errors)
    if meta.get("sales_start") != "manual":
        errors.append("sales_start must be 'manual'; approval must not start sales automatically")
    check_store_visibility(meta, errors)

    tags = meta.get("tags", {})
    if isinstance(tags, dict):
        for key, values in tags.items():
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                errors.append(f"tags for {key} must be a list of strings")
            elif len(values) > MAX_TAGS_PER_STAMP:
                errors.append(f"tags for {key} exceed {MAX_TAGS_PER_STAMP}")
    else:
        errors.append("tags must be an object")

    if zip_path.is_symlink() or not zip_path.is_file():
        errors.append(f"missing ZIP {zip_path}")
    elif type(count) is int and count in ALLOWED_COUNTS:
        submit_dir = project_dir / "submit"
        expected = validate_submission_names(submit_dir, count, errors, warnings)
        validate_png(submit_dir / "main.png", (240, 240), None, None, 0, errors, warnings)
        validate_png(submit_dir / "tab.png", (96, 74), None, None, 0, errors, warnings)
        for name in expected:
            validate_png(
                submit_dir / name,
                None,
                (80, 80),
                (370, 320),
                12,
                errors,
                warnings,
            )
        validate_stamp_sources(project_dir, submit_dir, count, errors)
        validate_zip(zip_path, submit_dir, ["main.png", "tab.png", *expected], errors)

    print(f"errors={len(errors)} warnings={len(warnings)}")
    for message in errors:
        print("ERROR", message)
    for message in warnings:
        print("WARN", message)
    if errors:
        raise SystemExit(1)
    print("READY: present metadata for P7 approval; P8 ends after registration input and preview confirmation")


if __name__ == "__main__":
    main()
