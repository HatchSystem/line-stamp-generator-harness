#!/usr/bin/env python3
"""Manage sticker projects under projects/<slug>/.

Each project is an isolated workspace with its own SESSION.md. The harness itself
(AGENTS.md, .agents/, tool-specific adapter directories, scripts/) is never touched by production work.

Public entry point (run from the repository root):

  python scripts/line_stamp.py project --root . list [--json]
  python scripts/line_stamp.py project --root . new --slug SLUG
  python scripts/line_stamp.py project --root . confirm-p0 --source photo|character ...
  python scripts/line_stamp.py project --root . confirm-design --image refs/design-v01.png ...
  python scripts/line_stamp.py project --root . confirm-three-view --image refs/three-view-v01.png
  python scripts/line_stamp.py project --root . record-learning --gate P5 --kind problem ...
  python scripts/line_stamp.py project --root . confirm-account --account-name NAME ...
  python scripts/line_stamp.py project --root . complete-production
  python scripts/line_stamp.py project --root . use SLUG
  python scripts/line_stamp.py project --root . status [--json]
  python scripts/line_stamp.py project --root . migrate [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from PIL import Image

from metadata_utils import DuplicateKeyError, loads_no_duplicates
from session_contract import require_design_evidence, sha256_file
from transaction_utils import LockUnavailableError, exclusive_lock

ALLOWED_COUNTS = (8, 16, 24, 32, 40)
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
WINDOWS_RESERVED_NAMES = {
    "ACTIVE",
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
PROJECT_DIRS = (
    "refs",
    "raw",
    "characters",
    "character-layers",
    "text-layers",
    "text-masks",
    "fonts",
    "stamps",
    "review",
    "submit",
    "meta",
)
DONE_STATES = {"production-complete", "local-complete"}
SESSION_SCHEMA_VERSION = 4
SUBMISSION_SCHEMA_VERSION = 3
DEPRECATED_SESSION_KEYS = frozenset({"adult", "consent", "rights"})
PRODUCTION_COMPLETE_MESSAGE = (
    "制作が完了しました。問題なければ審査リクエストを実施してください。"
)
LEARNING_KINDS = {"problem", "lesson"}
LEARNINGS_TEMPLATE = """# Project learnings

制作中に判明した問題と再利用可能な教訓だけを追記する。個人情報、素材の内容、
パスワード、認証コード、Cookie、APIキーなどの秘密情報は記録しない。

## Entries

"""


class ProjectPathError(RuntimeError):
    pass


def valid_slug(slug: str) -> bool:
    """Return whether a slug is portable across the supported agent environments."""
    return SLUG_RE.fullmatch(slug) is not None and slug.upper() not in WINDOWS_RESERVED_NAMES


def projects_root(root: str) -> Path:
    harness = Path(root).resolve()
    candidate = harness / "projects"
    if candidate.is_symlink():
        raise ProjectPathError(f"projects directory must not be a symlink: {candidate}")
    base = candidate.resolve()
    if candidate.exists() and base != candidate:
        raise ProjectPathError(f"projects directory must not use filesystem indirection: {candidate}")
    if not base.is_relative_to(harness):
        raise ProjectPathError(f"projects directory escapes harness root: {base}")
    return base


def project_directory(root: str, slug: str) -> Path:
    base = projects_root(root)
    candidate = base / slug
    if candidate.is_symlink():
        raise ProjectPathError(f"project directory must not be a symlink: {candidate}")
    project = candidate.resolve()
    if not project.is_relative_to(base):
        raise ProjectPathError(f"project path escapes projects/: {project}")
    return project


def project_file(project: Path, relative: str) -> Path:
    candidate = project / relative
    if candidate.is_symlink():
        raise ProjectPathError(f"project file must not be a symlink: {candidate}")
    path = candidate.resolve()
    if not path.is_relative_to(project.resolve()):
        raise ProjectPathError(f"project file escapes active project: {path}")
    return path


def active_file(root: str) -> Path:
    candidate = projects_root(root) / "ACTIVE"
    if candidate.is_symlink():
        raise ProjectPathError(f"ACTIVE must not be a symlink: {candidate}")
    return candidate


def parse_session(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def session_text(slug: str) -> str:
    """Create an isolated, deliberately incomplete P0 intake record."""
    return "\n".join(
        [
            "# SESSION",
            "",
            f"- schema_version: {SESSION_SCHEMA_VERSION}",
            f"- project: {slug}",
            "- materials: pending",
            "- source: unknown",
            "- count: 0",
            "- text: unknown",
            "- text_mode: unknown",
            "- text_check: n/a",
            "- text_mask_version: 0",
            "- gate: P0",
            "- character: pending",
            "- publish: unknown",
            "- lock: pending",
            "- three_view: pending",
            "- sample_candidates: 0",
            "- sample: not-started",
            "- review_version: 0",
            "- validation: not-run",
            "- submission: not-started",
            "- design_version: 0",
            "- design_evidence: pending",
            "- three_view_version: 0",
            "- account_name: pending",
            "- seller_id: pending",
            "- registration_target: pending",
            "- account_confirmed_at: pending",
            f"- notes: created {date.today().isoformat()}",
            "",
        ]
    )


def p0_updates(args: argparse.Namespace) -> tuple[dict[str, str], list[str]]:
    """Validate a complete P0 decision and return the SESSION transition to P1."""
    errors: list[str] = []
    character = args.character_name.strip()
    if not character or len(character) > 40 or any(char in character for char in "\r\n"):
        errors.append("character-name must be a single non-empty line of at most 40 characters")
    elif character.casefold() in {"pending", "unknown", "tbd", "n/a"} or re.fullmatch(
        r"<[^>]+>", character
    ):
        errors.append("character-name must be finalized and must not be a template placeholder")

    expected_modes = {"yes": {"font", "ai"}, "no": {"none"}}
    if args.text_mode not in expected_modes[args.text]:
        errors.append(
            f"text={args.text} requires text-mode in {sorted(expected_modes[args.text])}"
        )

    text_check = "not-run" if args.text_mode == "ai" else "n/a"
    updates = {
        "materials": args.materials,
        "source": args.source,
        "count": str(args.count),
        "text": args.text,
        "text_mode": args.text_mode,
        "text_check": text_check,
        "text_mask_version": "0",
        "gate": "P1",
        "character": character,
        "publish": args.publish,
        "sample_candidates": str(args.sample_candidates),
        "notes": f"P0 confirmed {date.today().isoformat()}",
    }
    return updates, errors


def reference_material_errors(project: Path) -> list[str]:
    """Require at least one direct, regular, non-symlink material in refs/."""
    errors: list[str] = []
    try:
        refs = project_file(project, "refs")
    except ProjectPathError as exc:
        return [str(exc)]
    if not refs.is_dir():
        return ["active project has no refs/ directory"]

    material_count = 0
    try:
        entries = list(refs.iterdir())
    except OSError as exc:
        return [f"cannot read refs/ directory: {exc}"]
    for entry in entries:
        if entry.is_symlink():
            errors.append(f"refs/ must not contain symlinks: {entry.name}")
            continue
        try:
            resolved = entry.resolve()
        except OSError as exc:
            errors.append(f"cannot resolve refs/{entry.name}: {exc}")
            continue
        if not resolved.is_relative_to(refs.resolve()):
            errors.append(f"refs/{entry.name} escapes the active project")
        elif entry.is_file():
            try:
                if entry.stat().st_size <= 0:
                    errors.append(f"refs/{entry.name} is empty")
                    continue
                with entry.open("rb") as material:
                    if not material.read(1):
                        errors.append(f"refs/{entry.name} is unreadable or empty")
                        continue
            except OSError as exc:
                errors.append(f"cannot read refs/{entry.name}: {exc}")
                continue
            material_count += 1
    if material_count == 0:
        errors.append("place at least one regular source file directly in the active project's refs/")
    return errors


def session_migration_updates(
    values: dict[str, str],
    *,
    materials_available: bool | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return meaning-preserving legacy -> v4 SESSION updates without writing files."""
    errors: list[str] = []
    raw_version = values.get("schema_version", "1")
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return {}, [f"SESSION schema_version={raw_version!r} is not an integer"]
    if version > SESSION_SCHEMA_VERSION:
        return {}, [f"SESSION schema_version={version} is newer than supported {SESSION_SCHEMA_VERSION}"]
    if version < 1:
        return {}, [f"SESSION schema_version={version} is unsupported"]

    publish = values.get("publish")
    allowed_publish = {"yes", "no", "private", "unknown", "local-only"}
    if publish not in allowed_publish:
        return {}, [f"SESSION publish={publish!r} is missing or unsupported"]

    updates: dict[str, str] = {}
    gate = values.get("gate", "")
    allowed_gates = {f"P{index}" for index in range(0, 9)}
    if version <= 3:
        allowed_gates.add("P9")
    if gate not in allowed_gates:
        return {}, [f"SESSION gate={gate!r} is unsupported for schema v{version}"]
    post_p0 = re.fullmatch(r"P[1-8]", gate) is not None or (
        version <= 3 and gate == "P9"
    )
    materials = values.get("materials")
    if materials is None:
        if version != 1:
            errors.append(
                f"SESSION schema v{version} is missing materials; repair it before continuing"
            )
        elif gate == "P0":
            # No approval is inferred: an unconfirmed intake remains pending.
            updates["materials"] = "pending"
        elif post_p0 and materials_available is True:
            # This records only an objective filesystem fact; no user declaration is inferred.
            updates["materials"] = "received"
        else:
            if post_p0:
                errors.append(
                    "legacy SESSION after P0 needs at least one verified, non-empty source file "
                    "in refs/ before materials can be migrated to received"
                )
            else:
                errors.append(
                    f"legacy SESSION gate={gate!r} cannot determine a safe materials state"
                )
    elif materials not in {"pending", "received"}:
        errors.append(f"SESSION materials={materials!r} is unsupported")
    elif post_p0 and materials == "pending":
        if version == 1 and materials_available is True:
            updates["materials"] = "received"
        elif version == 1:
            errors.append(
                "legacy SESSION after P0 cannot retain materials=pending; verify at least one "
                "non-empty source file in refs/ before migration"
            )
        else:
            errors.append("SESSION after P0 must have materials=received")

    if errors:
        return {}, errors
    if version != SESSION_SCHEMA_VERSION or raw_version != str(SESSION_SCHEMA_VERSION):
        updates["schema_version"] = str(SESSION_SCHEMA_VERSION)
    if publish in {"no", "private"}:
        updates["publish"] = "local-only"
    if version <= 3:
        for key, value in {
            "design_version": "0",
            "design_evidence": "pending",
            "three_view_version": "0",
            "account_name": "pending",
            "seller_id": "pending",
            "registration_target": "pending",
            "account_confirmed_at": "pending",
            "text_mask_version": "0",
        }.items():
            if key not in values:
                updates[key] = value
        legacy_submission = values.get("submission", "not-started")
        allowed_legacy_submission = {
            "not-started",
            "local-complete",
            "drafted",
            "requested",
            "approved",
            "rejected",
            "released",
        }
        if legacy_submission not in allowed_legacy_submission:
            errors.append(
                f"legacy SESSION submission={legacy_submission!r} is unsupported"
            )
        elif legacy_submission in {"requested", "approved", "rejected", "released"}:
            updates["submission"] = "production-complete"
            legacy_note = f"pre-v4 submission status was {legacy_submission}"
            existing_notes = values.get("notes", "").strip()
            updates["notes"] = (
                f"{existing_notes}; {legacy_note}" if existing_notes else legacy_note
            )
        elif "submission" not in values:
            updates["submission"] = "not-started"
        if gate == "P9":
            updates["gate"] = "P8"
    else:
        allowed_submission = {
            "not-started",
            "local-complete",
            "drafted",
            "production-complete",
        }
        if values.get("submission") not in allowed_submission:
            errors.append(
                f"SESSION submission={values.get('submission')!r} is unsupported for schema v4"
            )
    effective = {**values, **updates}
    for key in (
        "design_version",
        "design_evidence",
        "three_view_version",
        "account_name",
        "seller_id",
        "registration_target",
        "account_confirmed_at",
        "text_mask_version",
        "submission",
    ):
        if key not in effective or not effective[key]:
            errors.append(f"SESSION schema v4 requires field {key}")
    for key in ("design_version", "three_view_version", "text_mask_version"):
        if key in effective and re.fullmatch(r"[0-9]{1,9}", effective[key]) is None:
            errors.append(f"SESSION {key} must be a nonnegative integer")
    return updates, errors


def migrated_submission(meta: dict) -> tuple[dict, list[str], list[str]]:
    """Return a v3 metadata copy, its change descriptions, and blocking errors."""
    raw_version = meta.get("schema_version", 1)
    if type(raw_version) is int:
        version = raw_version
    elif (
        isinstance(raw_version, str)
        and len(raw_version) <= 9
        and re.fullmatch(r"[0-9]+", raw_version)
    ):
        version = int(raw_version)
    else:
        return dict(meta), [], [f"submission schema_version={raw_version!r} is not an integer"]
    if version > SUBMISSION_SCHEMA_VERSION:
        return dict(meta), [], [f"submission schema_version={version} is newer than supported {SUBMISSION_SCHEMA_VERSION}"]
    if version < 1:
        return dict(meta), [], [f"submission schema_version={version} is unsupported"]

    migrated = dict(meta)
    changes: list[str] = []
    if version != SUBMISSION_SCHEMA_VERSION or raw_version != SUBMISSION_SCHEMA_VERSION:
        migrated["schema_version"] = SUBMISSION_SCHEMA_VERSION
        changes.append(f"schema_version: {raw_version!r} -> {SUBMISSION_SCHEMA_VERSION}")
    if "sales_start" not in migrated:
        migrated["sales_start"] = "manual"
        changes.append("sales_start: missing -> manual")
    elif migrated["sales_start"] != "manual":
        return dict(meta), [], [
            f"submission sales_start={migrated['sales_start']!r}; choose manual explicitly before migrating"
        ]

    if "price_confirmed" not in migrated:
        # A migration cannot infer that the user checked the current external UI.
        migrated["price_confirmed"] = False
        changes.append("price_confirmed: missing -> false (user confirmation still required)")
    elif type(migrated["price_confirmed"]) is not bool:
        return dict(meta), [], ["submission price_confirmed must be a boolean"]

    legacy_private = migrated.get("private")
    visibility = migrated.get("store_visibility")
    if "private" in migrated and not isinstance(legacy_private, bool):
        return dict(meta), [], [f"submission private={legacy_private!r} is not a boolean"]
    if visibility is not None and not isinstance(visibility, str):
        return dict(meta), [], [f"submission store_visibility={visibility!r} must be a string"]
    if visibility is None and isinstance(legacy_private, bool):
        migrated["store_visibility"] = "private" if legacy_private else "public"
        migrated.pop("private", None)
        changes.append(f"private: {legacy_private!r} -> store_visibility: {migrated['store_visibility']}")
    elif visibility is not None and isinstance(legacy_private, bool):
        if visibility not in {"public", "private"}:
            return dict(meta), [], [f"submission store_visibility={visibility!r} is unsupported"]
        expected = "private" if legacy_private else "public"
        if visibility != expected:
            return dict(meta), [], [
                f"submission has conflicting private={legacy_private!r} and store_visibility={visibility!r}"
            ]
        migrated.pop("private", None)
        changes.append("remove deprecated private (store_visibility already matches)")
    elif visibility not in {"public", "private"}:
        return dict(meta), [], [
            "submission needs private: true|false or store_visibility: 'public'|'private' before migrating"
        ]
    if migrated.get("license_proof") == {"status": "not-required", "reference": ""}:
        migrated.pop("license_proof")
        changes.append("remove obsolete empty license_proof")
    return migrated, changes, []


def update_session_text(text: str, updates: dict[str, str]) -> str:
    """Update known SESSION keys while preserving comments and unknown fields."""
    had_final_newline = text.endswith("\n")
    lines = text.splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*-\s*)([a-z_]+)(\s*:\s*).*$", line)
        if match and match.group(2) in remaining:
            key = match.group(2)
            lines[index] = f"{match.group(1)}{key}{match.group(3)}{remaining.pop(key)}"
    if remaining:
        insertion = 2 if len(lines) >= 2 and lines[0].strip() == "# SESSION" else 0
        for key, value in reversed(list(remaining.items())):
            lines.insert(insertion, f"- {key}: {value}")
    result = "\n".join(lines)
    return result + ("\n" if had_final_newline else "")


def remove_session_keys(text: str, keys: set[str] | frozenset[str]) -> str:
    """Remove deprecated flat SESSION fields while preserving all unrelated content."""
    had_final_newline = text.endswith("\n")
    kept: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*([a-z_]+)\s*:", line)
        if match and match.group(1) in keys:
            continue
        kept.append(line)
    result = "\n".join(kept)
    return result + ("\n" if had_final_newline else "")


def parse_session_for_migration(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse SESSION while rejecting duplicate keys instead of silently choosing one."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if not match:
            continue
        key, value = match.groups()
        if key in values:
            errors.append(f"SESSION key {key!r} is duplicated (line {line_number})")
        else:
            values[key] = value.strip()
    return values, errors


def backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.pre-v{SESSION_SCHEMA_VERSION}-{timestamp}.bak")
    shutil.copy2(path, backup)
    return backup


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one file atomically through a temporary file beside the target."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def read_active(root: str) -> str | None:
    path = active_file(root)
    if not path.exists():
        return None
    if not path.is_file():
        raise ProjectPathError("ACTIVE must be a regular file")
    try:
        slug = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ProjectPathError(f"cannot read ACTIVE as UTF-8: {exc}") from exc
    if slug and not valid_slug(slug):
        raise ProjectPathError(f"ACTIVE contains invalid slug {slug!r}")
    return slug or None


def collect(root: str, active: str | None) -> list[dict[str, str]]:
    base = projects_root(root)
    rows: list[dict[str, str]] = []
    if not base.exists():
        return rows
    for session in sorted(base.glob("*/SESSION.md")):
        if session.is_symlink() or session.parent.is_symlink() or not session.resolve().is_relative_to(base):
            continue
        slug = session.parent.name
        diagnostic = ""
        try:
            source = session.read_text(encoding="utf-8")
            values, parse_errors = parse_session_for_migration(source)
            if parse_errors:
                diagnostic = "; ".join(parse_errors)
        except (OSError, UnicodeError) as exc:
            values = {}
            diagnostic = f"cannot read SESSION.md as UTF-8: {exc}"
        try:
            updated = datetime.fromtimestamp(session.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            updated = "?"
        rows.append(
            {
                "project": slug,
                "gate": values.get("gate", "?"),
                "source": values.get("source", "?"),
                "count": values.get("count", "?"),
                "text_mode": values.get("text_mode", "?"),
                "submission": values.get("submission", "?"),
                "updated": updated,
                "active": "yes" if slug == active else "",
                "done": "yes" if values.get("submission") in DONE_STATES else "",
                "error": diagnostic,
            }
        )
    return rows


def cmd_list(args: argparse.Namespace) -> int:
    active = read_active(args.root)
    rows = collect(args.root, active)
    if args.json:
        print(json.dumps({"active": active, "projects": rows}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("projects: none")
        return 0
    print(f"{'':2}{'project':<24}{'gate':<5}{'source':<11}{'count':<6}{'text':<6}{'submission':<13}updated")
    for row in rows:
        mark = "*" if row["active"] else " "
        print(f"{mark:2}{row['project']:<24}{row['gate']:<5}{row['source']:<11}{row['count']:<6}{row['text_mode']:<6}{row['submission']:<13}{row['updated']}")
    for row in rows:
        if row["error"]:
            print(f"WARN {row['project']}: {row['error']}", file=sys.stderr)
    print("(* = active)")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    if not valid_slug(args.slug):
        print(
            "ERROR slug must match ^[a-z0-9][a-z0-9-]{1,39}$, must not be a Windows "
            "reserved device name, and must not use a real name",
            file=sys.stderr,
        )
        return 1
    base = projects_root(args.root)
    project = project_directory(args.root, args.slug)
    if project.exists():
        print(
            f"ERROR project path '{args.slug}' already exists; "
            f"use `python scripts/line_stamp.py project --root . use {args.slug}` to resume it",
            file=sys.stderr,
        )
        return 1
    staging: Path | None = None
    installed = False
    rollback_errors: list[str] = []
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{args.slug}.new-", dir=base))
        for name in PROJECT_DIRS:
            (staging / name).mkdir(parents=True)
        (staging / "SESSION.md").write_text(session_text(args.slug), encoding="utf-8")
        (staging / "plan.md").write_text(
            "# Plan\n\nP3で承認されたセリフ・表情・ポーズを記録する。\n",
            encoding="utf-8",
        )
        (staging / "LEARNINGS.md").write_text(
            LEARNINGS_TEMPLATE,
            encoding="utf-8",
        )
        os.replace(staging, project)
        installed = True
        atomic_write_text(active_file(args.root), args.slug + "\n")
    except BaseException as exc:
        if installed and staging is not None:
            try:
                os.replace(project, staging)
                installed = False
            except BaseException as rollback_exc:
                rollback_errors.append(f"restore staged project {project}: {rollback_exc}")
        if staging is not None and staging.exists() and not installed:
            try:
                shutil.rmtree(staging)
            except BaseException as cleanup_exc:
                rollback_errors.append(f"remove staging {staging}: {cleanup_exc}")
        print(f"ERROR project creation failed: {exc}", file=sys.stderr)
        if rollback_errors:
            print(
                "ERROR creation rollback incomplete; preserve the reported path: "
                + "; ".join(rollback_errors),
                file=sys.stderr,
            )
        else:
            print("ROLLED BACK incomplete project creation", file=sys.stderr)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return 1
    print(project)
    print(f"ACTIVE={args.slug}")
    return 0


def cmd_confirm_p0(args: argparse.Namespace) -> int:
    """Persist one approved P0 intake and advance exactly one gate."""
    slug = read_active(args.root)
    if not slug:
        print("ERROR no active project; create or select one before confirming P0", file=sys.stderr)
        return 1
    project = project_directory(args.root, slug)
    session_path = project_file(project, "SESSION.md")
    if not session_path.is_file():
        print(f"ERROR active project '{slug}' has no SESSION.md", file=sys.stderr)
        return 1

    try:
        source = session_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"ERROR cannot read active SESSION.md as UTF-8: {exc}", file=sys.stderr)
        print("No project files changed.", file=sys.stderr)
        return 1
    values, parse_errors = parse_session_for_migration(source)
    errors = list(parse_errors)
    if values.get("schema_version") != str(SESSION_SCHEMA_VERSION):
        errors.append(
            f"SESSION schema_version must be {SESSION_SCHEMA_VERSION}; run project migrate first"
        )
    if values.get("project") != slug:
        errors.append(f"SESSION project={values.get('project')!r} does not match ACTIVE={slug!r}")
    if values.get("gate") != "P0":
        errors.append(f"confirm-p0 requires gate=P0 (found {values.get('gate')!r})")
    deprecated = sorted(DEPRECATED_SESSION_KEYS.intersection(values))
    if deprecated:
        errors.append(
            "SESSION contains deprecated fields "
            f"{deprecated}; run project migrate before confirming P0"
        )
    errors.extend(reference_material_errors(project))
    updates, intake_errors = p0_updates(args)
    errors.extend(intake_errors)
    if errors:
        for message in errors:
            print(f"ERROR {message}", file=sys.stderr)
        print("No project files changed.", file=sys.stderr)
        return 1

    try:
        atomic_write_text(session_path, update_session_text(source, updates))
    except OSError as exc:
        print(f"ERROR could not persist P0 confirmation: {exc}", file=sys.stderr)
        print("SESSION was not replaced.", file=sys.stderr)
        return 1
    print(
        f"CONFIRMED P0 project={slug} source={updates['source']} count={updates['count']} "
        f"text_mode={updates['text_mode']} publish={updates['publish']} gate=P1"
    )
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    if not valid_slug(args.slug):
        print("ERROR invalid project slug", file=sys.stderr)
        return 1
    session = project_file(project_directory(args.root, args.slug), "SESSION.md")
    if not session.is_file():
        print(f"ERROR project '{args.slug}' not found (no SESSION.md)", file=sys.stderr)
        return 1
    try:
        source = session.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"ERROR cannot read project '{args.slug}' SESSION.md as UTF-8: {exc}", file=sys.stderr)
        print("ACTIVE was not changed.", file=sys.stderr)
        return 1
    values, errors = parse_session_for_migration(source)
    if values.get("project") != args.slug:
        errors.append(f"SESSION project={values.get('project')!r} does not match slug={args.slug!r}")
    if errors:
        for message in errors:
            print(f"ERROR {message}", file=sys.stderr)
        print("ACTIVE was not changed.", file=sys.stderr)
        return 1
    try:
        atomic_write_text(active_file(args.root), args.slug + "\n")
    except OSError as exc:
        print(f"ERROR could not select project '{args.slug}': {exc}", file=sys.stderr)
        print("ACTIVE was not replaced.", file=sys.stderr)
        return 1
    print(f"ACTIVE={args.slug} gate={values.get('gate', '?')} submission={values.get('submission', '?')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    active = read_active(args.root)
    if not active:
        if args.json:
            print(json.dumps({"active": None}, ensure_ascii=False))
        else:
            print(
                "ACTIVE=none — `python scripts/line_stamp.py project --root . list` で選択するか "
                "同じ公開 CLI の `project ... new` で作成する"
            )
        return 2
    if not valid_slug(active):
        print(f"ERROR ACTIVE contains invalid slug {active!r}", file=sys.stderr)
        return 1
    session = project_file(project_directory(args.root, active), "SESSION.md")
    if not session.exists():
        print(f"ERROR ACTIVE points to '{active}' but SESSION.md is missing", file=sys.stderr)
        return 1
    try:
        source = session.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"ERROR cannot read active SESSION.md as UTF-8: {exc}", file=sys.stderr)
        return 1
    values, errors = parse_session_for_migration(source)
    if values.get("project") != active:
        errors.append(f"SESSION project={values.get('project')!r} does not match ACTIVE={active!r}")
    if errors:
        for message in errors:
            print(f"ERROR {message}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"active": active, "session_path": str(session), "session": values}, ensure_ascii=False, indent=2))
    else:
        print(f"ACTIVE={active}")
        print(f"SESSION={session}")
        for key, value in values.items():
            print(f"- {key}: {value}")
    return 0


def active_session(args: argparse.Namespace) -> tuple[str, Path, Path, str, dict[str, str]]:
    """Return the selected project's stable SESSION snapshot for state commands."""
    slug = read_active(args.root)
    if not slug or not valid_slug(slug):
        raise ProjectPathError("select a valid active project before changing project state")
    project = project_directory(args.root, slug)
    session_path = project_file(project, "SESSION.md")
    if not session_path.is_file():
        raise ProjectPathError(f"active project {slug!r} has no SESSION.md")
    source = session_path.read_text(encoding="utf-8")
    values, errors = parse_session_for_migration(source)
    if errors:
        raise ProjectPathError("; ".join(errors))
    if values.get("project") != slug:
        raise ProjectPathError(
            f"SESSION project={values.get('project')!r} does not match ACTIVE={slug!r}"
        )
    if values.get("schema_version") != str(SESSION_SCHEMA_VERSION):
        raise ProjectPathError(
            f"SESSION schema_version must be {SESSION_SCHEMA_VERSION}; run project migrate first"
        )
    return slug, project, session_path, source, values


def checked_record_value(label: str, value: str, *, max_length: int = 1000) -> str:
    """Keep project records single-line and free of common credential material."""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length or any(char in cleaned for char in "\r\n"):
        raise ValueError(f"{label} must be one non-empty line of at most {max_length} characters")
    folded = cleaned.casefold()
    forbidden = (
        "password",
        "passwd",
        "api key",
        "api_key",
        "access token",
        "cookie",
        "パスワード",
        "認証コード",
        "秘密鍵",
    )
    if any(token in folded for token in forbidden):
        raise ValueError(f"{label} appears to contain credential or secret material")
    return cleaned


def notes_with_event(values: dict[str, str], event: str) -> str:
    existing = values.get("notes", "").strip()
    return f"{existing}; {event}" if existing else event


def sha256_path(path: Path) -> str:
    return sha256_file(path)


def checked_ref_file(project: Path, value: str, label: str) -> Path:
    if (project / "refs").is_symlink():
        raise ValueError("project refs/ must not be a symlink")
    raw = Path(value)
    if raw.is_absolute() or raw.parts[:1] != ("refs",):
        raise ValueError(f"{label} must be a project-relative path under refs/")
    path = project_file(project, raw.as_posix())
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {value}")
    return path


def require_png_file(path: Path, label: str) -> None:
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.width <= 0 or opened.height <= 0:
                raise ValueError(f"{label} must be a non-empty PNG image")
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} is not a readable PNG image: {exc}") from exc


def require_reference_image(path: Path) -> None:
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.width <= 0 or opened.height <= 0:
                raise ValueError("reference image is empty")
    except (OSError, ValueError) as exc:
        raise ValueError(f"reference is not a readable image: {path.name}: {exc}") from exc


def next_versioned_ref(project: Path, prefix: str, suffix: str) -> int:
    pattern = re.compile(rf"{re.escape(prefix)}-v([0-9]{{2,}}){re.escape(suffix)}")
    versions = [
        int(match.group(1))
        for path in (project / "refs").glob(f"{prefix}-v*{suffix}")
        if (match := pattern.fullmatch(path.name))
    ]
    return max(versions, default=0) + 1


def write_new_text_files(files: list[tuple[Path, str]]) -> None:
    created: list[Path] = []
    try:
        for path, content in files:
            with path.open("x", encoding="utf-8", newline="\n") as destination:
                destination.write(content)
            created.append(path)
    except BaseException:
        for path in reversed(created):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        raise


def cmd_confirm_design(args: argparse.Namespace) -> int:
    """Create an immutable P1 design contract and invalidate downstream approvals."""
    created: list[Path] = []
    try:
        slug, project, session_path, session_source, values = active_session(args)
        if values.get("gate") not in {f"P{index}" for index in range(1, 9)}:
            raise ValueError("design confirmation requires an active Phase P1 through P8")
        version = next_versioned_ref(project, "design", ".json")
        image = checked_ref_file(project, args.image, "design image")
        require_png_file(image, "design image")
        expected_image = project / "refs" / f"design-v{version:02d}.png"
        if image != expected_image.resolve():
            raise ValueError(
                f"design image must use the next versioned name refs/{expected_image.name}"
            )
        references = [
            checked_ref_file(project, value, "reference") for value in args.reference
        ]
        if len(references) != len(set(references)):
            raise ValueError("reference inputs must not contain duplicates")
        if image in references:
            raise ValueError("reference inputs must not use the generated design image itself")
        for reference in references:
            require_reference_image(reference)
        fields = {
            "髪形": checked_record_value("hairstyle", args.hairstyle, max_length=500),
            "服装": checked_record_value("clothing", args.clothing, max_length=500),
            "目": checked_record_value("eyes", args.eyes, max_length=500),
            "固定装飾": checked_record_value("accessories", args.accessories, max_length=500),
        }
        if not 1.0 <= args.head_ratio <= 5.0:
            raise ValueError("head-ratio must be from 1.0 through 5.0")
        colors = [value.upper() for value in args.color]
        if not colors or any(re.fullmatch(r"#[0-9A-F]{6}", value) is None for value in colors):
            raise ValueError("each --color must be a six-digit HEX value such as #1A2B3C")
        if len(colors) != len(set(colors)) or len(colors) > 12:
            raise ValueError("use 1-12 distinct --color values")
        spec_path = project / "refs" / f"design-v{version:02d}.md"
        evidence_path = project / "refs" / f"design-v{version:02d}.json"
        spec_text = "\n".join(
            [
                f"# Design v{version:02d}",
                "",
                f"- 髪形: {fields['髪形']}",
                f"- 頭身: {args.head_ratio:g}",
                f"- 服装: {fields['服装']}",
                f"- 配色: {', '.join(colors)}",
                f"- 目: {fields['目']}",
                f"- 固定装飾: {fields['固定装飾']}",
                "- 背景: transparent",
                f"- デザイン画像: refs/{image.name}",
                "- 参考画像: " + ", ".join(f"refs/{path.name}" for path in references),
                "",
            ]
        )
        evidence = {
            "schema_version": 1,
            "version": version,
            "project": slug,
            "gate": "P1",
            "checklist": {
                "hairstyle": fields["髪形"],
                "head_ratio": args.head_ratio,
                "clothing": fields["服装"],
                "palette": colors,
                "eyes": fields["目"],
                "accessories": fields["固定装飾"],
                "background": "transparent",
            },
            "design_file": f"refs/{image.name}",
            "design_sha256": sha256_path(image),
            "spec_file": f"refs/{spec_path.name}",
            "spec_sha256": hashlib.sha256(spec_text.encode("utf-8")).hexdigest(),
            "references": [
                {"file": f"refs/{path.name}", "sha256": sha256_path(path)}
                for path in references
            ],
        }
        evidence_text = json.dumps(
            evidence, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n"
        write_new_text_files([(spec_path, spec_text), (evidence_path, evidence_text)])
        created.extend((spec_path, evidence_path))
        updates = {
            "gate": "P2",
            "design_version": str(version),
            "design_evidence": f"refs/{evidence_path.name}",
            "lock": "approved",
            "three_view": "pending",
            "three_view_version": "0",
            "sample": "not-started",
            "review_version": "0",
            "text_check": "not-run" if values.get("text_mode") == "ai" else "n/a",
            "text_mask_version": "0",
            "validation": "not-run",
            "submission": "not-started",
            "account_name": "pending",
            "seller_id": "pending",
            "registration_target": "pending",
            "account_confirmed_at": "pending",
            "notes": notes_with_event(values, f"P1 design v{version:02d} confirmed"),
        }
        atomic_write_text(session_path, update_session_text(session_source, updates))
    except (OSError, UnicodeError, ValueError, ProjectPathError) as exc:
        for path in reversed(created):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        print(f"ERROR could not confirm P1 design: {exc}", file=sys.stderr)
        return 1
    print(f"P1 complete: design v{version:02d} approved for {slug}; next Phase is P2")
    return 0


def cmd_confirm_three_view(args: argparse.Namespace) -> int:
    """Bind the approved P2 image to the exact P1 design evidence."""
    created: list[Path] = []
    try:
        slug, project, session_path, session_source, values = active_session(args)
        if values.get("gate") != "P2":
            raise ValueError(f"three-view confirmation requires gate=P2 (found {values.get('gate')!r})")
        design = require_design_evidence(project, values)
        version = next_versioned_ref(project, "three-view", ".json")
        image = checked_ref_file(project, args.image, "three-view image")
        require_png_file(image, "three-view image")
        expected_image = project / "refs" / f"three-view-v{version:02d}.png"
        if image != expected_image.resolve():
            raise ValueError(
                f"three-view image must use the next versioned name refs/{expected_image.name}"
            )
        evidence_path = project / "refs" / f"three-view-v{version:02d}.json"
        evidence = {
            "schema_version": 1,
            "version": version,
            "project": slug,
            "gate": "P2",
            "three_view_file": f"refs/{image.name}",
            "three_view_sha256": sha256_path(image),
            "design_evidence": values["design_evidence"],
            "design_evidence_sha256": sha256_path(design),
        }
        evidence_text = json.dumps(
            evidence, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n"
        write_new_text_files([(evidence_path, evidence_text)])
        created.append(evidence_path)
        updates = {
            "gate": "P3",
            "three_view": "approved",
            "three_view_version": str(version),
            "notes": notes_with_event(values, f"P2 three-view v{version:02d} confirmed"),
        }
        atomic_write_text(session_path, update_session_text(session_source, updates))
    except (OSError, UnicodeError, ValueError, ProjectPathError) as exc:
        for path in reversed(created):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        print(f"ERROR could not confirm P2 three-view: {exc}", file=sys.stderr)
        return 1
    print(f"P2 complete: three-view v{version:02d} approved for {slug}; next Phase is P3")
    return 0


def cmd_record_learning(args: argparse.Namespace) -> int:
    """Append one structured production observation without overwriting prior entries."""
    try:
        slug, project, _, _, values = active_session(args)
        if args.gate not in {f"P{index}" for index in range(0, 9)}:
            raise ValueError("gate must be P0 through P8")
        fields = {
            "事象": checked_record_value("summary", args.summary),
            "影響": checked_record_value("impact", args.impact),
            "原因": checked_record_value("cause", args.cause),
            "対処": checked_record_value("resolution", args.resolution),
            "改善候補": checked_record_value("candidate", args.candidate),
        }
        if args.kind not in LEARNING_KINDS:
            raise ValueError(f"kind must be one of {sorted(LEARNING_KINDS)}")
        learning_path = project_file(project, "LEARNINGS.md")
        if learning_path.is_symlink():
            raise ValueError("LEARNINGS.md must not be a symlink")
        if learning_path.exists():
            source = learning_path.read_text(encoding="utf-8")
            if not source.startswith("# Project learnings\n"):
                raise ValueError("LEARNINGS.md does not use the canonical project template")
        else:
            source = LEARNINGS_TEMPLATE
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        block = [
            f"### {timestamp} [{args.kind}] {fields['事象']}",
            "",
            f"- Phase: {args.gate}",
            *(f"- {label}: {value}" for label, value in fields.items()),
            "",
        ]
        atomic_write_text(learning_path, source.rstrip() + "\n\n" + "\n".join(block))
    except (OSError, UnicodeError, ValueError, ProjectPathError) as exc:
        print(f"ERROR could not record project learning: {exc}", file=sys.stderr)
        return 1
    print(f"RECORDED {slug} {args.gate} {args.kind} in {learning_path}")
    return 0


def cmd_confirm_account(args: argparse.Namespace) -> int:
    """Persist the user-confirmed P8 account identity before any registration input."""
    try:
        slug, _, session_path, source, values = active_session(args)
        required = {
            "gate": "P8",
            "publish": "yes",
            "validation": "ok",
            "submission": "drafted",
        }
        for key, expected in required.items():
            if values.get(key) != expected:
                raise ValueError(
                    f"P8 account confirmation requires {key}={expected} "
                    f"(found {values.get(key)!r})"
                )
        account_name = checked_record_value("account-name", args.account_name, max_length=200)
        seller_id = checked_record_value("seller-id", args.seller_id, max_length=200)
        target = checked_record_value(
            "registration-target", args.registration_target, max_length=300
        )
        confirmed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        updates = {
            "account_name": account_name,
            "seller_id": seller_id,
            "registration_target": target,
            "account_confirmed_at": confirmed_at,
            "notes": notes_with_event(values, f"P8 account confirmed {confirmed_at}"),
        }
        atomic_write_text(session_path, update_session_text(source, updates))
    except (OSError, UnicodeError, ValueError, ProjectPathError) as exc:
        print(f"ERROR could not confirm P8 account: {exc}", file=sys.stderr)
        return 1
    print(f"CONFIRMED P8 account for {slug}: {account_name} / {seller_id} / {target}")
    return 0


def cmd_complete_production(args: argparse.Namespace) -> int:
    """Finish the reversible P8 workflow without tracking the review request."""
    try:
        _, _, session_path, source, values = active_session(args)
        if values.get("submission") == "production-complete":
            print(PRODUCTION_COMPLETE_MESSAGE)
            return 0
        required = {
            "gate": "P8",
            "publish": "yes",
            "validation": "ok",
            "submission": "drafted",
        }
        for key, expected in required.items():
            if values.get(key) != expected:
                raise ValueError(
                    f"production completion requires {key}={expected} "
                    f"(found {values.get(key)!r})"
                )
        for key in (
            "account_name",
            "seller_id",
            "registration_target",
            "account_confirmed_at",
        ):
            if values.get(key, "pending") in {"", "pending", "unknown"}:
                raise ValueError(f"production completion requires confirmed SESSION {key}")
        repeated_identity = {
            "account_name": checked_record_value(
                "account-name", args.account_name, max_length=200
            ),
            "seller_id": checked_record_value("seller-id", args.seller_id, max_length=200),
            "registration_target": checked_record_value(
                "registration-target", args.registration_target, max_length=300
            ),
        }
        for key, value in repeated_identity.items():
            if values.get(key) != value:
                raise ValueError(
                    f"current {key} does not match the user-confirmed P8 account record"
                )
        if not args.preview_confirmed:
            raise ValueError("production completion requires --preview-confirmed")
        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        updates = {
            "submission": "production-complete",
            "notes": notes_with_event(values, f"production completed {completed_at}"),
        }
        atomic_write_text(session_path, update_session_text(source, updates))
    except (OSError, UnicodeError, ValueError, ProjectPathError) as exc:
        print(f"ERROR could not complete production: {exc}", file=sys.stderr)
        return 1
    print(PRODUCTION_COMPLETE_MESSAGE)
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Inspect the active project by default; write only with explicit --apply."""
    slug = read_active(args.root)
    if not slug:
        print("ERROR ACTIVE=none; select a project before migration", file=sys.stderr)
        return 1
    if not valid_slug(slug):
        print(f"ERROR ACTIVE contains invalid slug {slug!r}", file=sys.stderr)
        return 1
    project = project_directory(args.root, slug)
    session_path = project_file(project, "SESSION.md")
    if not session_path.is_file():
        print(f"ERROR active project '{slug}' has no SESSION.md", file=sys.stderr)
        return 1

    try:
        session_source = session_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"ERROR cannot read SESSION.md as UTF-8: {exc}", file=sys.stderr)
        print("No files changed.", file=sys.stderr)
        return 1
    session_values, errors = parse_session_for_migration(session_source)
    session_updates: dict[str, str] = {}
    if not errors and session_values.get("project") != slug:
        errors.append(
            f"SESSION project={session_values.get('project')!r} does not match ACTIVE={slug!r}"
        )
    materials_available: bool | None = None
    try:
        session_version = int(session_values.get("schema_version", "1"))
    except (TypeError, ValueError):
        session_version = None
    if (
        not errors
        and session_version == 1
        and re.fullmatch(r"P[1-9]", session_values.get("gate", ""))
    ):
        material_errors = reference_material_errors(project)
        materials_available = not material_errors
        errors.extend(f"legacy material verification: {message}" for message in material_errors)
    if not errors:
        session_updates, session_errors = session_migration_updates(
            session_values,
            materials_available=materials_available,
        )
        errors.extend(session_errors)
    session_removals = sorted(
        key for key in DEPRECATED_SESSION_KEYS if key in session_values
    )
    submission_path = project_file(project, "meta/submission.json")
    learning_path = project_file(project, "LEARNINGS.md")
    if learning_path.is_symlink() or (learning_path.exists() and not learning_path.is_file()):
        errors.append("LEARNINGS.md must be a regular non-symlink file")
    learning_missing = not learning_path.exists()
    migrated_meta: dict | None = None
    meta_changes: list[str] = []
    if submission_path.exists():
        try:
            submission_source = submission_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read submission JSON as UTF-8: {exc}")
        else:
            try:
                parsed = loads_no_duplicates(submission_source)
            except ValueError as exc:
                errors.append(f"submission JSON is invalid: {exc}")
            else:
                if not isinstance(parsed, dict):
                    errors.append("submission JSON root must be an object")
                else:
                    migrated_meta, meta_changes, meta_errors = migrated_submission(parsed)
                    errors.extend(meta_errors)

    if errors:
        for message in errors:
            print("ERROR", message, file=sys.stderr)
        print("No files changed.", file=sys.stderr)
        return 1

    planned = [f"SESSION {key}: {value}" for key, value in session_updates.items()]
    planned.extend(f"SESSION remove deprecated field: {key}" for key in session_removals)
    planned.extend(f"submission {change}" for change in meta_changes)
    if learning_missing:
        planned.append("create project LEARNINGS.md")
    if not planned:
        print(f"project '{slug}' already uses schema v{SESSION_SCHEMA_VERSION}; no files changed")
        return 0
    for change in planned:
        print("PLAN", change)
    if not args.apply:
        print(
            "DRY RUN: no files changed; rerun with `python scripts/line_stamp.py project "
            "--root . migrate --apply` after reviewing the plan"
        )
        return 0

    writes: list[tuple[Path, str]] = []
    if session_updates or session_removals:
        migrated_session = update_session_text(session_source, session_updates)
        migrated_session = remove_session_keys(migrated_session, set(session_removals))
        writes.append((session_path, migrated_session))
    if migrated_meta is not None and meta_changes:
        try:
            rendered_meta = json.dumps(
                migrated_meta,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ) + "\n"
        except (TypeError, ValueError) as exc:
            print(f"ERROR migrated submission cannot be encoded as strict JSON: {exc}", file=sys.stderr)
            print("No files changed.", file=sys.stderr)
            return 1
        writes.append((submission_path, rendered_meta))
    if learning_missing:
        writes.append((learning_path, LEARNINGS_TEMPLATE))
    backups: dict[Path, Path] = {}
    new_paths: set[Path] = set()
    try:
        for path, _ in writes:
            if path.exists():
                backups[path] = backup_file(path)
            else:
                new_paths.add(path)
    except OSError as exc:
        print(f"ERROR could not create migration backups: {exc}", file=sys.stderr)
        cleanup_errors: list[str] = []
        for backup in backups.values():
            try:
                backup.unlink()
            except OSError as cleanup_exc:
                cleanup_errors.append(f"{backup}: {cleanup_exc}")
        if cleanup_errors:
            print("WARN unused backup cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
        print("No original project files changed.", file=sys.stderr)
        return 1
    try:
        for path, content in writes:
            atomic_write_text(path, content)
    except BaseException as exc:
        restore_errors: list[str] = []
        for path, backup in backups.items():
            try:
                atomic_write_bytes(path, backup.read_bytes())
            except Exception as restore_exc:
                restore_errors.append(f"{path}: {restore_exc}")
        for path in new_paths:
            try:
                if path.exists() and not path.is_symlink():
                    path.unlink()
            except Exception as restore_exc:
                restore_errors.append(f"{path}: {restore_exc}")
        print(f"ERROR migration write failed: {exc}", file=sys.stderr)
        if restore_errors:
            print("ERROR rollback incomplete: " + "; ".join(restore_errors), file=sys.stderr)
        else:
            print("ROLLED BACK original files from backups", file=sys.stderr)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return 1
    for backup in backups.values():
        print(f"BACKUP {backup}")
    if not submission_path.exists():
        print("NOTE submission.json does not exist; create it from the v3 template at P7")
    print(f"MIGRATED project '{slug}' to schema v{SESSION_SCHEMA_VERSION}")
    return 0


def dispatch_command(args: argparse.Namespace) -> int:
    """Serialize shared ACTIVE changes and state mutations across cooperating agents."""
    state_commands = {
        "confirm-p0",
        "confirm-design",
        "confirm-three-view",
        "migrate",
        "record-learning",
        "confirm-account",
        "complete-production",
    }
    if args.command not in {"new", "use", *state_commands}:
        return args.func(args)

    base = projects_root(args.root)
    if base.is_symlink() or not base.is_dir():
        raise ProjectPathError(f"projects must be a regular directory: {base}")
    with exclusive_lock(base / ".line-stamp-projects.lock", f"project command {args.command}"):
        if args.command in state_commands:
            slug = read_active(args.root)
            if slug:
                project = project_directory(args.root, slug)
                if project.is_dir():
                    with exclusive_lock(
                        project / ".line-stamp-project.lock",
                        f"project state command {args.command}",
                    ):
                        # The command reads ACTIVE and SESSION only after both locks
                        # are held, so validation and the eventual write share one snapshot.
                        return args.func(args)
        return args.func(args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage isolated sticker projects under projects/")
    parser.add_argument("--root", default=".", help="harness root (contains projects/)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list projects")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_new = sub.add_parser("new", help="create an isolated P0 project and make it active")
    p_new.add_argument(
        "--slug",
        required=True,
        help="2-40 lowercase letters/digits/hyphens, starting with a letter or digit; never a real name",
    )
    p_new.set_defaults(func=cmd_new)

    p_confirm = sub.add_parser("confirm-p0", help="validate approved intake fields and advance P0 to P1")
    p_confirm.add_argument("--materials", choices=("received",), required=True)
    p_confirm.add_argument("--source", choices=("photo", "character"), required=True)
    p_confirm.add_argument("--count", type=int, choices=ALLOWED_COUNTS, required=True)
    p_confirm.add_argument("--text", choices=("yes", "no"), required=True)
    p_confirm.add_argument("--text-mode", choices=("font", "ai", "none"), required=True)
    p_confirm.add_argument("--character-name", required=True, help="public display name; never a real name")
    p_confirm.add_argument("--sample-candidates", type=int, choices=(1, 2, 3), required=True)
    p_confirm.add_argument("--publish", choices=("yes", "local-only"), required=True)
    p_confirm.set_defaults(func=cmd_confirm_p0)

    p_design = sub.add_parser(
        "confirm-design",
        help="persist an immutable approved P1 design sheet and advance to P2",
    )
    p_design.add_argument("--image", required=True)
    p_design.add_argument("--reference", action="append", required=True)
    p_design.add_argument("--hairstyle", required=True)
    p_design.add_argument("--head-ratio", type=float, required=True)
    p_design.add_argument("--clothing", required=True)
    p_design.add_argument("--color", action="append", required=True)
    p_design.add_argument("--eyes", required=True)
    p_design.add_argument("--accessories", required=True)
    p_design.set_defaults(func=cmd_confirm_design)

    p_three_view = sub.add_parser(
        "confirm-three-view",
        help="bind an approved P2 three-view image to the current design evidence",
    )
    p_three_view.add_argument("--image", required=True)
    p_three_view.set_defaults(func=cmd_confirm_three_view)

    p_use = sub.add_parser("use", help="select an existing project")
    p_use.add_argument("slug")
    p_use.set_defaults(func=cmd_use)

    p_status = sub.add_parser("status", help="show the active project")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_learning = sub.add_parser(
        "record-learning",
        help="append one structured problem or lesson to the active project",
    )
    p_learning.add_argument("--gate", required=True)
    p_learning.add_argument("--kind", choices=sorted(LEARNING_KINDS), required=True)
    p_learning.add_argument("--summary", required=True)
    p_learning.add_argument("--impact", required=True)
    p_learning.add_argument("--cause", required=True)
    p_learning.add_argument("--resolution", required=True)
    p_learning.add_argument("--candidate", required=True)
    p_learning.set_defaults(func=cmd_record_learning)

    p_account = sub.add_parser(
        "confirm-account",
        help="record the user-confirmed Creators Market identity before P8 input",
    )
    p_account.add_argument("--account-name", required=True)
    p_account.add_argument("--seller-id", required=True)
    p_account.add_argument("--registration-target", required=True)
    p_account.set_defaults(func=cmd_confirm_account)

    p_complete = sub.add_parser(
        "complete-production",
        help="mark reversible P8 registration work complete and stop",
    )
    p_complete.add_argument("--account-name", required=True)
    p_complete.add_argument("--seller-id", required=True)
    p_complete.add_argument("--registration-target", required=True)
    p_complete.add_argument("--preview-confirmed", action="store_true", required=True)
    p_complete.set_defaults(func=cmd_complete_production)

    p_migrate = sub.add_parser(
        "migrate",
        help="inspect or migrate an active legacy project to SESSION schema v4",
    )
    p_migrate.add_argument("--apply", action="store_true", help="back up and atomically write the planned changes")
    p_migrate.set_defaults(func=cmd_migrate)

    args = parser.parse_args()
    try:
        return dispatch_command(args)
    except (ProjectPathError, LockUnavailableError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
