"""Strict shared SESSION contract for artifact-producing commands."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from metadata_utils import loads_no_duplicates


STATIC_COUNTS = {8, 16, 24, 32, 40}
DEPRECATED_SESSION_KEYS = {"adult", "consent", "rights"}
TEXT_REPORT_RE = re.compile(r"text-check-v([0-9]+)\.json")
REVIEW_EVIDENCE_RE = re.compile(r"review-v([0-9]{2,})\.json")


def project_stamp_name(index: int) -> str:
    """Return the canonical filename used by project-internal stamp artifacts."""
    if type(index) is not int or not 1 <= index <= max(STATIC_COUNTS):
        raise ValueError(f"stamp index must be an integer from 1 to {max(STATIC_COUNTS)}")
    return f"stamp{index:02d}.png"


def submission_stamp_name(index: int) -> str:
    """Return the filename recognized by Creators Market ZIP uploads."""
    if type(index) is not int or not 1 <= index <= max(STATIC_COUNTS):
        raise ValueError(f"stamp index must be an integer from 1 to {max(STATIC_COUNTS)}")
    return f"{index:02d}.png"


def read_regular_bytes(path: Path) -> bytes:
    """Read one stable regular file while rejecting path swaps and in-place changes."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"evidence file must be regular and non-symlink: {path}")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"evidence file must be regular: {path}")
            payload = handle.read()
            after = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"cannot read evidence file {path}: {exc}") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(current.st_mode)
        or not os.path.samestat(before, current)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError(f"evidence file changed while it was read: {path}")
    return payload


def sha256_file(path: Path) -> str:
    """Hash one stable regular, non-symlink evidence input."""
    return hashlib.sha256(read_regular_bytes(path)).hexdigest()


def require_complete_text_evidence(project_dir: Path, count: int) -> None:
    """Require the latest AI text report to bind every current P5 input by hash."""
    review_dir = project_dir / "review"
    if review_dir.is_symlink() or not review_dir.is_dir():
        raise ValueError("P6 AI text_check=ok requires a regular review/ directory")
    reports = [
        (int(match.group(1)), path)
        for path in review_dir.glob("text-check-v*.json")
        if (match := TEXT_REPORT_RE.fullmatch(path.name))
    ]
    if not reports:
        raise ValueError("P6 AI text_check=ok requires a versioned P5 text-check JSON report")
    report_version, report_path = max(reports, key=lambda pair: pair[0])
    if report_path.is_symlink() or not report_path.is_file():
        raise ValueError("latest P5 text evidence JSON must be a regular non-symlink file")
    markdown_path = report_path.with_suffix(".md")
    if markdown_path.is_symlink() or not markdown_path.is_file():
        raise ValueError(f"P5 text evidence is missing paired report {markdown_path.name}")
    try:
        report = loads_no_duplicates(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read strict P5 text evidence {report_path.name}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError("P5 text evidence root must be an object")
    if (
        report.get("schema_version") != 1
        or report.get("version") != report_version
        or report.get("project") != project_dir.name
        or report.get("gate") != "P5"
        or report.get("scope") != "all"
        or report.get("session_count") != count
    ):
        raise ValueError("latest text evidence is not a complete P5 report for this SESSION")

    manifest_path = project_dir / "manifest.json"
    if report.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("P5 text evidence does not match the current manifest.json")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("P5 text evidence rows do not match SESSION count")
    by_id: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError("P5 text evidence contains an invalid row")
        row_id = row["id"]
        if row_id in by_id:
            raise ValueError(f"P5 text evidence duplicates id {row_id}")
        by_id[row_id] = row
    expected_ids = set(range(1, count + 1))
    if set(by_id) != expected_ids:
        raise ValueError("P5 text evidence ids are not exactly 1..SESSION count")
    for row_id in sorted(expected_ids):
        name = project_stamp_name(row_id)
        row = by_id[row_id]
        status = row.get("status")
        if not isinstance(status, str) or status not in {
            "match",
            "near",
            "mismatch",
            "visual-required",
        }:
            raise ValueError(f"P5 text evidence has an incomplete status for {name}")
        if not isinstance(row.get("expected"), str) or not row["expected"].strip():
            raise ValueError(f"P5 text evidence has empty expected text for {name}")
        if row.get("file") != name or row.get("sha256") != sha256_file(project_dir / "stamps" / name):
            raise ValueError(f"P5 text evidence does not match current {name}")


def require_review_evidence(project_dir: Path, count: int, version: int) -> None:
    """Bind a user-approved review version to every current source stamp by hash."""
    if version <= 0:
        raise ValueError("P6 requires a positive SESSION review_version approved at P5")
    review_dir = project_dir / "review"
    image_path = review_dir / f"review-v{version:02d}.png"
    evidence_path = review_dir / f"review-v{version:02d}.json"
    if review_dir.is_symlink() or not review_dir.is_dir():
        raise ValueError("review evidence requires a regular project review/ directory")
    for label, path in (("review image", image_path), ("review evidence", evidence_path)):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{label} must be a regular non-symlink file: {path.name}")
    match = REVIEW_EVIDENCE_RE.fullmatch(evidence_path.name)
    if match is None or int(match.group(1)) != version:
        raise ValueError("review evidence filename does not match SESSION review_version")
    try:
        evidence = loads_no_duplicates(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read strict review evidence {evidence_path.name}: {exc}") from exc
    if not isinstance(evidence, dict):
        raise ValueError("review evidence root must be an object")
    if (
        evidence.get("schema_version") != 1
        or evidence.get("version") != version
        or evidence.get("project") != project_dir.name
        or evidence.get("gate") != "P5"
        or evidence.get("session_count") != count
        or evidence.get("review_file") != image_path.name
        or evidence.get("review_sha256") != sha256_file(image_path)
    ):
        raise ValueError("review evidence does not match SESSION or its versioned review image")
    rows = evidence.get("stamps")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("review evidence stamp rows do not match SESSION count")
    by_id: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError("review evidence contains an invalid stamp row")
        row_id = row["id"]
        if row_id in by_id:
            raise ValueError(f"review evidence duplicates id {row_id}")
        by_id[row_id] = row
    expected_ids = set(range(1, count + 1))
    if set(by_id) != expected_ids:
        raise ValueError("review evidence ids are not exactly 1..SESSION count")
    for row_id in sorted(expected_ids):
        name = project_stamp_name(row_id)
        row = by_id[row_id]
        if row.get("file") != name or row.get("sha256") != sha256_file(
            project_dir / "stamps" / name
        ):
            raise ValueError(f"review evidence does not match current {name}")


def load_static_session(project_dir: Path, allowed_gates: set[str]) -> dict[str, str]:
    """Load an unambiguous schema-v3 SESSION and validate its static-pack fields."""
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

    if values.get("schema_version") != "3":
        raise ValueError("SESSION schema_version must be 3")
    deprecated = sorted(DEPRECATED_SESSION_KEYS.intersection(values))
    if deprecated:
        raise ValueError(
            f"SESSION contains deprecated fields {deprecated}; run project migrate first"
        )
    if values.get("project") != project_dir.name:
        raise ValueError(
            f"SESSION project={values.get('project')!r} does not match {project_dir.name!r}"
        )
    gate = values.get("gate")
    if gate not in allowed_gates:
        raise ValueError(
            f"SESSION gate={gate!r} is not valid for this command; expected {sorted(allowed_gates)}"
        )
    if values.get("materials") != "received":
        raise ValueError("artifact commands after P0 require SESSION materials=received")
    count_value = values.get("count", "")
    if count_value not in {str(value) for value in STATIC_COUNTS}:
        raise ValueError(f"SESSION count={count_value!r} is not a supported static count")
    count = int(count_value)
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
        if gate in {"P4", "P5"} and text_check != "not-run":
            raise ValueError("SESSION text_mode=ai at P4/P5 requires text_check=not-run")
        if gate == "P6":
            if text_check != "ok":
                raise ValueError("SESSION text_mode=ai at P6 requires text_check=ok")
            require_complete_text_evidence(project_dir, count)
    elif text_check != "n/a":
        raise ValueError(f"SESSION text_mode={text_mode!r} requires text_check=n/a")
    if gate == "P6":
        review_value = values.get("review_version", "")
        if re.fullmatch(r"[1-9][0-9]{0,8}", review_value) is None:
            raise ValueError("SESSION review_version must be a positive version approved at P5")
        require_review_evidence(project_dir, count, int(review_value))
    return values


def session_count(session: dict[str, str]) -> int:
    """Return the already-validated static count."""
    return int(session["count"])
