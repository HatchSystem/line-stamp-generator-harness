#!/usr/bin/env python3
"""Stable repository entry point for the line-stamp-generator skill scripts.

The implementation stays beside the portable Agent Skill under `.agents/skills/`.
This launcher keeps documented commands independent from an agent vendor's adapter path.
"""
from __future__ import annotations

from importlib import import_module
from importlib import util as importlib_util
import os
import re
import sys
from pathlib import Path


COMMANDS = {
    "project": "project.py",
    "preprocess-character": "preprocess_character.py",
    "compose-static": "compose_static.py",
    "verify-text": "verify_text.py",
    "make-contact-sheet": "make_contact_sheet.py",
    "package-static": "package_static.py",
    "validate-pack": "validate_pack.py",
    "check-publish-ready": "check_publish_ready.py",
    "self-test": "self_test.py",
}
ARTIFACT_COMMANDS = {
    "preprocess-character",
    "compose-static",
    "verify-text",
    "make-contact-sheet",
    "package-static",
    "validate-pack",
    "check-publish-ready",
}
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
WINDOWS_RESERVED_NAMES = {
    "ACTIVE", "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
FACADE_PROJECT_ENV = "LINE_STAMP_FACADE_PROJECT"


def usage() -> str:
    names = "\n  ".join(COMMANDS)
    return (
        "Usage: python scripts/line_stamp.py <command> [args...]\n\n"
        f"Commands:\n  {names}\n\n"
        "Run `python scripts/line_stamp.py <command> --help` for command-specific options."
    )


def configure_utf8_stdio() -> None:
    """Keep redirected Windows output usable when the host code page is narrow."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Embedded hosts may expose an immutable stream; their wrapper owns encoding.
            pass


def main() -> int:
    configure_utf8_stdio()
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(usage())
        return 0

    command = sys.argv[1]
    script_name = COMMANDS.get(command)
    if script_name is None:
        print(f"ERROR unknown command: {command}\n\n{usage()}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parent.parent
    script_dir = repo_root / ".agents" / "skills" / "line-stamp-generator" / "scripts"
    script_path = script_dir / script_name
    if not script_path.is_file():
        print(f"ERROR skill script not found: {script_path}", file=sys.stderr)
        return 1

    command_args = sys.argv[2:]
    original_argv = sys.argv[:]
    original_path = sys.path[:]
    original_facade_project = os.environ.pop(FACADE_PROJECT_ENV, None)
    try:
        sys.path.insert(0, str(script_dir))
        module_name = f"_line_stamp_{command.replace('-', '_')}"
        spec = importlib_util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            print(f"ERROR cannot load skill script: {script_path}", file=sys.stderr)
            return 1
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        entrypoint = getattr(module, "main", None)
        if not callable(entrypoint):
            print(f"ERROR skill script has no callable main(): {script_path}", file=sys.stderr)
            return 1

        sys.argv = [f"python scripts/line_stamp.py {command}", *command_args]
        if command in ARTIFACT_COMMANDS and not any(
            argument in {"-h", "--help"} for argument in command_args
        ):
            projects_dir = repo_root / "projects"
            if projects_dir.is_symlink() or not projects_dir.is_dir():
                print("ERROR repository projects/ must be a regular directory", file=sys.stderr)
                return 1
            transaction_utils = import_module("transaction_utils")
            exclusive_lock = transaction_utils.exclusive_lock
            try:
                with exclusive_lock(
                    projects_dir / ".line-stamp-projects.lock",
                    f"public artifact command {command}",
                ):
                    active_path = projects_dir / "ACTIVE"
                    if active_path.is_symlink() or not active_path.is_file():
                        print("ERROR select an active project before running an artifact command", file=sys.stderr)
                        return 1
                    try:
                        slug = active_path.read_text(encoding="utf-8").strip()
                    except (OSError, UnicodeError) as exc:
                        print(f"ERROR cannot read projects/ACTIVE as UTF-8: {exc}", file=sys.stderr)
                        return 1
                    if SLUG_RE.fullmatch(slug) is None or slug.upper() in WINDOWS_RESERVED_NAMES:
                        print(f"ERROR projects/ACTIVE contains an invalid slug: {slug!r}", file=sys.stderr)
                        return 1
                    project_dir = projects_dir / slug
                    if project_dir.is_symlink() or not project_dir.is_dir():
                        print(f"ERROR active project is missing or a symlink: {project_dir}", file=sys.stderr)
                        return 1
                    selected_project = project_dir.resolve()
                    os.environ[FACADE_PROJECT_ENV] = str(selected_project)
                    with exclusive_lock(
                        selected_project / ".line-stamp-project.lock",
                        f"public artifact command {command}",
                    ):
                        result = entrypoint()
            except transaction_utils.LockUnavailableError as exc:
                print(f"ERROR another agent is updating project state: {exc}", file=sys.stderr)
                return 1
        else:
            result = entrypoint()
        return result if isinstance(result, int) else 0
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path
        if original_facade_project is None:
            os.environ.pop(FACADE_PROJECT_ENV, None)
        else:
            os.environ[FACADE_PROJECT_ENV] = original_facade_project


if __name__ == "__main__":
    raise SystemExit(main())
