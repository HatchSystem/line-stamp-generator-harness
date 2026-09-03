#!/usr/bin/env python3
"""Manage sticker projects under projects/<slug>/.

Each project is an isolated workspace with its own SESSION.md. The harness itself
(AGENTS.md, .claude/, scripts/) is never touched by production work.

  project.py list   [--root .] [--json]        # all projects with gate/submission
  project.py new    --slug SLUG --source photo|character --count N [--text yes|no]
  project.py use    SLUG                        # set projects/ACTIVE
  project.py status [--root .] [--json]        # active project and its SESSION values
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ALLOWED_COUNTS = (8, 16, 24, 32, 40)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
PROJECT_DIRS = ("refs", "raw", "characters", "character-layers", "text-layers", "stamps", "review", "submit", "meta")
DONE_STATES = {"released"}


def projects_root(root: str) -> Path:
    return Path(root).resolve() / "projects"


def active_file(root: str) -> Path:
    return projects_root(root) / "ACTIVE"


def parse_session(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def session_text(slug: str, source: str, count: int, text: str, text_mode: str) -> str:
    if text == "no":
        text_mode = "none"
    text_check = "n/a" if text_mode != "ai" else "not-run"
    return "\n".join(
        [
            "# SESSION",
            "",
            f"- project: {slug}",
            f"- source: {source}",
            f"- count: {count}",
            f"- text: {text}",
            f"- text_mode: {text_mode}",
            f"- text_check: {text_check}",
            "- gate: P0",
            "- character: pending",
            "- rights: unknown",
            "- adult: unknown",
            "- consent: unknown",
            "- publish: unknown",
            "- lock: pending",
            "- three_view: pending",
            "- sample_candidates: 1",
            "- sample: not-started",
            "- review_version: 0",
            "- validation: not-run",
            "- submission: not-started",
            f"- notes: created {date.today().isoformat()}",
            "",
        ]
    )


def read_active(root: str) -> str | None:
    path = active_file(root)
    if not path.exists():
        return None
    slug = path.read_text(encoding="utf-8").strip()
    return slug or None


def collect(root: str) -> list[dict[str, str]]:
    base = projects_root(root)
    active = read_active(root)
    rows: list[dict[str, str]] = []
    if not base.exists():
        return rows
    for session in sorted(base.glob("*/SESSION.md")):
        values = parse_session(session)
        slug = session.parent.name
        updated = datetime.fromtimestamp(session.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
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
    print("(* = active)")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    if not SLUG_RE.match(args.slug):
        print("ERROR slug must match ^[a-z0-9][a-z0-9-]{1,39}$ (do not use real names)", file=sys.stderr)
        return 1
    if args.count not in ALLOWED_COUNTS:
        print(f"ERROR count must be one of {ALLOWED_COUNTS}", file=sys.stderr)
        return 1
    project = projects_root(args.root) / args.slug
    session = project / "SESSION.md"
    if session.exists():
        print(f"ERROR project '{args.slug}' already exists; use `project.py use {args.slug}` to resume it", file=sys.stderr)
        return 1
    for name in PROJECT_DIRS:
        (project / name).mkdir(parents=True, exist_ok=True)
    session.write_text(session_text(args.slug, args.source, args.count, args.text, args.text_mode), encoding="utf-8")
    (project / "plan.md").write_text("# Plan\n\nP3で承認されたセリフとポーズを記録する。\n", encoding="utf-8")
    active_file(args.root).write_text(args.slug + "\n", encoding="utf-8")
    print(project)
    print(f"ACTIVE={args.slug}")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    session = projects_root(args.root) / args.slug / "SESSION.md"
    if not session.exists():
        print(f"ERROR project '{args.slug}' not found (no SESSION.md)", file=sys.stderr)
        return 1
    active_file(args.root).write_text(args.slug + "\n", encoding="utf-8")
    values = parse_session(session)
    print(f"ACTIVE={args.slug} gate={values.get('gate', '?')} submission={values.get('submission', '?')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    active = read_active(args.root)
    if not active:
        if args.json:
            print(json.dumps({"active": None}, ensure_ascii=False))
        else:
            print("ACTIVE=none — `project.py list` で選択するか `project.py new` で作成する")
        return 2
    session = projects_root(args.root) / active / "SESSION.md"
    if not session.exists():
        print(f"ERROR ACTIVE points to '{active}' but SESSION.md is missing", file=sys.stderr)
        return 1
    values = parse_session(session)
    if args.json:
        print(json.dumps({"active": active, "session_path": str(session), "session": values}, ensure_ascii=False, indent=2))
    else:
        print(f"ACTIVE={active}")
        print(f"SESSION={session}")
        for key, value in values.items():
            print(f"- {key}: {value}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage isolated sticker projects under projects/")
    parser.add_argument("--root", default=".", help="harness root (contains projects/)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list projects")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_new = sub.add_parser("new", help="create a project and make it active")
    p_new.add_argument("--slug", required=True, help="lowercase letters, digits, hyphen; never a real name")
    p_new.add_argument("--source", choices=("photo", "character"), required=True)
    p_new.add_argument("--count", type=int, required=True)
    p_new.add_argument("--text", choices=("yes", "no"), default="yes")
    p_new.add_argument("--text-mode", choices=("font", "ai"), default="font", help="font: 埋め込みフォントで描画 / ai: 生成AIに文字を描かせ verify_text.py で検査")
    p_new.set_defaults(func=cmd_new)

    p_use = sub.add_parser("use", help="select an existing project")
    p_use.add_argument("slug")
    p_use.set_defaults(func=cmd_use)

    p_status = sub.add_parser("status", help="show the active project")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
