#!/usr/bin/env python3
"""Manage sticker projects under projects/<slug>/.

Each project is an isolated workspace with its own SESSION.md. The harness itself
(AGENTS.md, .agents/, tool-specific adapter directories, scripts/) is never touched by production work.

Public entry point (run from the repository root):

  python scripts/line_stamp.py project --root . list [--json]
  python scripts/line_stamp.py project --root . new --slug SLUG
  python scripts/line_stamp.py project --root . confirm-p0 --source photo|character ...
  python scripts/line_stamp.py project --root . use SLUG
  python scripts/line_stamp.py project --root . status [--json]
  python scripts/line_stamp.py project --root . migrate [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from metadata_utils import DuplicateKeyError, loads_no_duplicates
from transaction_utils import LockUnavailableError, exclusive_lock

ALLOWED_COUNTS = (8, 16, 24, 32, 40)
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
PROJECT_DIRS = ("refs", "raw", "characters", "character-layers", "text-layers", "fonts", "stamps", "review", "submit", "meta")
DONE_STATES = {"released", "local-complete"}
SESSION_SCHEMA_VERSION = 2
SUBMISSION_SCHEMA_VERSION = 2


class ProjectPathError(RuntimeError):
    pass


def valid_slug(slug: str) -> bool:
    """Return whether a slug is portable across the supported agent environments."""
    return SLUG_RE.fullmatch(slug) is not None and slug.upper() not in WINDOWS_RESERVED_NAMES


def projects_root(root: str) -> Path:
    harness = Path(root).resolve()
    base = (harness / "projects").resolve()
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
            "- gate: P0",
            "- character: pending",
            "- rights: unknown",
            "- adult: unknown",
            "- consent: unknown",
            "- publish: unknown",
            "- lock: pending",
            "- three_view: pending",
            "- sample_candidates: 0",
            "- sample: not-started",
            "- review_version: 0",
            "- validation: not-run",
            "- submission: not-started",
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

    if args.rights not in {"own", "licensed"}:
        errors.append("rights must be own or licensed; unknown rights stop production")

    if args.source == "photo":
        if args.consent != "yes":
            errors.append("photo production requires explicit subject consent=yes")
        if args.adult == "n/a":
            errors.append("photo adult status must be yes, no, or unknown")
        if args.publish == "yes" and args.adult != "yes":
            errors.append("photo publication requires an explicit adult=yes; use local-only otherwise")
    elif args.adult != "n/a" or args.consent != "n/a":
        errors.append("character source requires adult=n/a and consent=n/a")

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
        "gate": "P1",
        "character": character,
        "rights": args.rights,
        "adult": args.adult,
        "consent": args.consent,
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
    """Return meaning-preserving v1 -> v2 SESSION updates without writing files."""
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
    materials = values.get("materials")
    if materials is None:
        if version != 1:
            errors.append("SESSION schema v2 is missing materials; repair it before continuing")
        elif values.get("gate") == "P0":
            # No approval is inferred: an unconfirmed intake remains pending.
            updates["materials"] = "pending"
        elif re.fullmatch(r"P[1-9]", values.get("gate", "")) and materials_available is True:
            # This records only an objective filesystem fact. Rights and consent are
            # preserved from the legacy SESSION and are never inferred here.
            updates["materials"] = "received"
        else:
            if re.fullmatch(r"P[1-9]", values.get("gate", "")):
                errors.append(
                    "legacy SESSION after P0 needs at least one verified, non-empty source file "
                    "in refs/ before materials can be migrated to received"
                )
            else:
                errors.append(
                    f"legacy SESSION gate={values.get('gate')!r} cannot determine a safe materials state"
                )
    elif materials not in {"pending", "received"}:
        errors.append(f"SESSION materials={materials!r} is unsupported")

    if errors:
        return {}, errors
    if version != SESSION_SCHEMA_VERSION or raw_version != str(SESSION_SCHEMA_VERSION):
        updates["schema_version"] = str(SESSION_SCHEMA_VERSION)
    if publish in {"no", "private"}:
        updates["publish"] = "local-only"
    return updates, errors


def migrated_submission(meta: dict) -> tuple[dict, list[str], list[str]]:
    """Return a v2 metadata copy, its change descriptions, and blocking errors."""
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
    backup = path.with_name(f"{path.name}.pre-v2-{timestamp}.bak")
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


def collect(root: str) -> list[dict[str, str]]:
    base = projects_root(root)
    active = read_active(root)
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
    rows = collect(args.root)
    if args.json:
        print(json.dumps({"active": read_active(args.root), "projects": rows}, ensure_ascii=False, indent=2))
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
        and "materials" not in session_values
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
    submission_path = project_file(project, "meta/submission.json")
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
    planned.extend(f"submission {change}" for change in meta_changes)
    if not planned:
        print(f"project '{slug}' already uses schema v2; no files changed")
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
    if session_updates:
        writes.append((session_path, update_session_text(session_source, session_updates)))
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
    backups: dict[Path, Path] = {}
    try:
        for path, _ in writes:
            backups[path] = backup_file(path)
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
        print("NOTE submission.json does not exist; create it from the v2 template at P7")
    print(f"MIGRATED project '{slug}' to schema v2")
    return 0


def dispatch_command(args: argparse.Namespace) -> int:
    """Serialize shared ACTIVE changes and state mutations across cooperating agents."""
    if args.command not in {"new", "use", "confirm-p0", "migrate"}:
        return args.func(args)

    base = projects_root(args.root)
    if base.is_symlink() or not base.is_dir():
        raise ProjectPathError(f"projects must be a regular directory: {base}")
    with exclusive_lock(base / ".line-stamp-projects.lock", f"project command {args.command}"):
        if args.command in {"confirm-p0", "migrate"}:
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
    p_confirm.add_argument("--rights", choices=("own", "licensed", "unknown"), required=True)
    p_confirm.add_argument("--adult", choices=("yes", "no", "unknown", "n/a"), required=True)
    p_confirm.add_argument("--consent", choices=("yes", "no", "unknown", "n/a"), required=True)
    p_confirm.set_defaults(func=cmd_confirm_p0)

    p_use = sub.add_parser("use", help="select an existing project")
    p_use.add_argument("slug")
    p_use.set_defaults(func=cmd_use)

    p_status = sub.add_parser("status", help="show the active project")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_migrate = sub.add_parser("migrate", help="inspect or migrate the active v1 project to schema v2")
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
