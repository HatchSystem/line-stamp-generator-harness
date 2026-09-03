"""Strict shared SESSION contract for artifact-producing commands."""
from __future__ import annotations

import re
from pathlib import Path


STATIC_COUNTS = {8, 16, 24, 32, 40}


def load_static_session(project_dir: Path, allowed_gates: set[str]) -> dict[str, str]:
    """Load an unambiguous schema-v2 SESSION and validate its static-pack fields."""
    session_path = project_dir / "SESSION.md"
    if session_path.is_symlink() or not session_path.is_file():
        raise ValueError("active project SESSION.md must be a regular non-symlink file")
    try:
        lines = session_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read SESSION.md as UTF-8: {exc}") from exc

    values: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", line.strip())
        if not match:
            continue
        key, value = match.groups()
        if key in values:
            raise ValueError(f"SESSION key {key!r} is duplicated (line {line_number})")
        values[key] = value.strip()

    if values.get("schema_version") != "2":
        raise ValueError("SESSION schema_version must be 2")
    if values.get("project") != project_dir.name:
        raise ValueError(
            f"SESSION project={values.get('project')!r} does not match {project_dir.name!r}"
        )
    gate = values.get("gate")
    if gate not in allowed_gates:
        raise ValueError(
            f"SESSION gate={gate!r} is not valid for this command; expected {sorted(allowed_gates)}"
        )
    try:
        count = int(values.get("count", ""))
    except ValueError as exc:
        raise ValueError(f"SESSION count={values.get('count')!r} is not an integer") from exc
    if count not in STATIC_COUNTS:
        raise ValueError(f"SESSION count={count!r} is not a supported static count")
    text = values.get("text")
    text_mode = values.get("text_mode")
    if (text == "yes" and text_mode not in {"font", "ai"}) or (
        text == "no" and text_mode != "none"
    ):
        raise ValueError(
            f"SESSION text={text!r} and text_mode={text_mode!r} are inconsistent"
        )
    if text not in {"yes", "no"}:
        raise ValueError(f"SESSION text={text!r} is unsupported")
    text_check = values.get("text_check")
    if text_mode == "ai":
        if gate == "P6" and text_check != "ok":
            raise ValueError("SESSION text_mode=ai at P6 requires text_check=ok")
        if gate in {"P4", "P5"} and text_check not in {"not-run", "ok"}:
            raise ValueError(
                "SESSION text_mode=ai at P4/P5 requires text_check=not-run or ok"
            )
    elif text_check != "n/a":
        raise ValueError(f"SESSION text_mode={text_mode!r} requires text_check=n/a")
    return values


def session_count(session: dict[str, str]) -> int:
    """Return the already-validated static count."""
    return int(session["count"])
