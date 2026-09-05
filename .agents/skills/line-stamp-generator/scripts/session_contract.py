"""Strict shared SESSION contract for artifact-producing commands."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path

from metadata_utils import loads_no_duplicates


STATIC_COUNTS = {8, 16, 24, 32, 40}
DEPRECATED_SESSION_KEYS = {"adult", "consent", "rights"}
TEXT_REPORT_RE = re.compile(r"text-check-v([0-9]+)\.json")
REVIEW_EVIDENCE_RE = re.compile(r"review-v([0-9]{2,})\.json")
HEX_COLOR_RE = re.compile(r"#[0-9A-F]{6}")


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


def project_relative_evidence(project_dir: Path, value: object, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a project-relative path")
    raw = Path(value)
    if raw.is_absolute() or raw.parts[:1] != ("refs",):
        raise ValueError(f"{label} must stay under project refs/")
    path = (project_dir / raw).resolve()
    if not path.is_relative_to(project_dir.resolve() / "refs"):
        raise ValueError(f"{label} escapes project refs/")
    return path


def require_design_evidence(project_dir: Path, session: dict[str, str]) -> Path:
    """Validate the immutable P1 checklist, image, and reference hashes."""
    version_value = session.get("design_version", "")
    if re.fullmatch(r"[1-9][0-9]{0,8}", version_value) is None:
        raise ValueError("approved artifacts require a positive SESSION design_version")
    version = int(version_value)
    expected_path = project_dir / "refs" / f"design-v{version:02d}.json"
    evidence_path = project_relative_evidence(
        project_dir, session.get("design_evidence"), "SESSION design_evidence"
    )
    if evidence_path != expected_path.resolve():
        raise ValueError("SESSION design_evidence does not match design_version")
    try:
        evidence = loads_no_duplicates(read_regular_bytes(evidence_path).decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read strict design evidence: {exc}") from exc
    if not isinstance(evidence, dict) or any(
        (
            evidence.get("schema_version") != 1,
            evidence.get("version") != version,
            evidence.get("project") != project_dir.name,
            evidence.get("gate") != "P1",
        )
    ):
        raise ValueError("design evidence does not match SESSION P1 contract")
    checklist = evidence.get("checklist")
    required_text = ("hairstyle", "clothing", "eyes", "accessories")
    if not isinstance(checklist, dict) or any(
        not isinstance(checklist.get(key), str) or not checklist[key].strip()
        for key in required_text
    ):
        raise ValueError("design evidence checklist has missing text fields")
    ratio = checklist.get("head_ratio") if isinstance(checklist, dict) else None
    if type(ratio) not in {int, float} or not 1.0 <= float(ratio) <= 5.0:
        raise ValueError("design evidence head_ratio must be numeric from 1.0 through 5.0")
    palette = checklist.get("palette") if isinstance(checklist, dict) else None
    if (
        not isinstance(palette, list)
        or not palette
        or len(palette) > 12
        or any(not isinstance(value, str) or HEX_COLOR_RE.fullmatch(value) is None for value in palette)
        or len(palette) != len(set(palette))
    ):
        raise ValueError("design evidence palette must contain 1-12 distinct uppercase HEX colors")
    if checklist.get("background") != "transparent":
        raise ValueError("design evidence background must be transparent")
    image_path = project_relative_evidence(project_dir, evidence.get("design_file"), "design_file")
    spec_path = project_relative_evidence(project_dir, evidence.get("spec_file"), "spec_file")
    if (
        image_path.name != f"design-v{version:02d}.png"
        or spec_path.name != f"design-v{version:02d}.md"
        or evidence.get("design_sha256") != sha256_file(image_path)
        or evidence.get("spec_sha256") != sha256_file(spec_path)
    ):
        raise ValueError("design evidence files or hashes do not match the approved version")
    references = evidence.get("references")
    if not isinstance(references, list) or not references:
        raise ValueError("design evidence requires at least one reference image")
    for item in references:
        if not isinstance(item, dict):
            raise ValueError("design evidence contains an invalid reference row")
        reference_path = project_relative_evidence(project_dir, item.get("file"), "reference")
        if item.get("sha256") != sha256_file(reference_path):
            raise ValueError(f"design reference hash changed: {reference_path.name}")
    return evidence_path


def require_three_view_evidence(project_dir: Path, session: dict[str, str]) -> Path:
    """Bind P2 approval to the exact current P1 evidence and image bytes."""
    design_path = require_design_evidence(project_dir, session)
    version_value = session.get("three_view_version", "")
    if session.get("three_view") != "approved" or re.fullmatch(
        r"[1-9][0-9]{0,8}", version_value
    ) is None:
        raise ValueError("approved artifacts require a positive P2 three_view_version")
    version = int(version_value)
    evidence_path = project_dir / "refs" / f"three-view-v{version:02d}.json"
    try:
        evidence = loads_no_duplicates(read_regular_bytes(evidence_path).decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read strict three-view evidence: {exc}") from exc
    image_path = project_dir / "refs" / f"three-view-v{version:02d}.png"
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema_version") != 1
        or evidence.get("version") != version
        or evidence.get("project") != project_dir.name
        or evidence.get("gate") != "P2"
        or evidence.get("three_view_file") != f"refs/{image_path.name}"
        or evidence.get("three_view_sha256") != sha256_file(image_path)
        or evidence.get("design_evidence") != session.get("design_evidence")
        or evidence.get("design_evidence_sha256") != sha256_file(design_path)
    ):
        raise ValueError("three-view evidence does not match the current approved P1 design")
    return evidence_path


def visual_text_matches(expected: str, recognized: str) -> bool:
    """Ignore layout whitespace, preserving punctuation and glyph distinctions."""

    def normalized(value: str) -> str:
        return "".join(unicodedata.normalize("NFC", value).split())

    return bool(normalized(expected)) and normalized(expected) == normalized(recognized)


def require_complete_text_evidence(
    project_dir: Path, count: int, mask_version: int | None = None
) -> None:
    """Require visual observations (or approved legacy evidence) and current masks."""
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
        report.get("schema_version") not in (2, 3)
        or report.get("version") != report_version
        or report.get("project") != project_dir.name
        or report.get("gate") != "P5"
        or report.get("scope") != "all"
        or report.get("session_count") != count
    ):
        raise ValueError("latest text evidence is not a complete P5 report for this SESSION")
    if mask_version is not None and report_version != mask_version:
        raise ValueError("SESSION text_mask_version does not match latest P5 text evidence")
    visual = report.get("schema_version") == 3
    if visual:
        if report.get("method") != "ai-visual":
            raise ValueError("P5 text evidence requires method ai-visual")
    else:
        # Read-only compatibility for previously approved schema 2 reports.
        if report.get("automatic_available") is not True:
            raise ValueError("P5 text evidence has no automatic checker; P6 remains blocked")
        provider = report.get("automatic_provider")
        model = report.get("automatic_model")
        method = report.get("automatic_method")
        if (
            method not in ("ocr", "vision")
            or not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(model, str)
            or not model.strip()
        ):
            raise ValueError("P5 text evidence is missing its automatic provider or model")
        if method == "vision":
            source_value = report.get("vision_evidence_file")
            if not isinstance(source_value, str):
                raise ValueError("P5 vision fallback is missing its source evidence file")
            source_raw = Path(source_value)
            if source_raw.is_absolute() or source_raw.parts[:1] not in {("review",), ("meta",)}:
                raise ValueError("P5 vision evidence file must stay under project review/ or meta/")
            source_path = (project_dir / source_raw).resolve()
            if not source_path.is_relative_to(project_dir.resolve()):
                raise ValueError("P5 vision evidence file escapes the project")
            if report.get("vision_evidence_sha256") != sha256_file(source_path):
                raise ValueError("P5 vision evidence source has changed")
        elif report.get("vision_evidence_file") is not None or report.get(
            "vision_evidence_sha256"
        ) is not None:
            raise ValueError("P5 OCR evidence must not claim a vision fallback source")

    manifest_path = project_dir / "manifest.json"
    if report.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("P5 text evidence does not match the current manifest.json")
    expected_by_id: dict[int, str] = {}
    if visual:
        manifest = loads_no_duplicates(read_regular_bytes(manifest_path).decode("utf-8"))
        items = manifest.get("items") if isinstance(manifest, dict) else None
        if not isinstance(items, list):
            raise ValueError("P5 visual review requires manifest items")
        for item in items:
            if not isinstance(item, dict) or type(item.get("id")) is not int:
                raise ValueError("P5 visual review manifest has an invalid id")
            item_id = item["id"]
            value = item.get("text")
            if isinstance(value, list) and value and all(isinstance(line, str) for line in value):
                value = "".join(value)
            if item_id in expected_by_id or not isinstance(value, str) or not value.strip():
                raise ValueError("P5 visual review manifest has duplicate ids or invalid text")
            expected_by_id[item_id] = value
        if set(expected_by_id) != set(range(1, count + 1)):
            raise ValueError("P5 visual review manifest ids do not match SESSION count")
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
        }:
            raise ValueError(f"P5 text evidence has an incomplete status for {name}")
        if not isinstance(row.get("expected"), str) or not row["expected"].strip():
            raise ValueError(f"P5 text evidence has empty expected text for {name}")
        if row.get("file") != name or row.get("sha256") != sha256_file(project_dir / "stamps" / name):
            raise ValueError(f"P5 text evidence does not match current {name}")
        if visual:
            recognized = row.get("recognized")
            if (
                status != "match"
                or row["expected"] != expected_by_id[row_id]
                or not isinstance(recognized, str)
                or not visual_text_matches(row["expected"], recognized)
            ):
                raise ValueError(f"P5 AI visual review is incomplete or mismatched for {name}")
        elif row.get("automatic_provider") != provider or not isinstance(
            row.get("automatic_text"), str
        ):
            raise ValueError(f"P5 automatic text evidence is incomplete for {name}")
        expected_mask = f"text-masks/v{report_version:02d}/{name}"
        if row.get("mask_file") != expected_mask:
            raise ValueError(f"P5 text mask path does not match {name}")
        mask_path = project_dir / expected_mask
        if row.get("mask_sha256") != sha256_file(mask_path):
            raise ValueError(f"P5 text mask does not match current {name}")


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
        or evidence.get("presentation") != "all-stamps-light-dark"
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
    """Load an unambiguous schema-v4 SESSION and validate its static-pack fields."""
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

    if values.get("schema_version") != "4":
        raise ValueError("SESSION schema_version must be 4")
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
    if gate in {"P4", "P5", "P6"}:
        require_three_view_evidence(project_dir, values)
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
            mask_value = values.get("text_mask_version", "")
            if re.fullmatch(r"[1-9][0-9]{0,8}", mask_value) is None:
                raise ValueError(
                    "SESSION text_mode=ai at P6 requires a positive text_mask_version"
                )
            require_complete_text_evidence(project_dir, count, int(mask_value))
    else:
        if text_check != "n/a":
            raise ValueError(f"SESSION text_mode={text_mode!r} requires text_check=n/a")
        if values.get("text_mask_version") != "0":
            raise ValueError(
                f"SESSION text_mode={text_mode!r} requires text_mask_version=0"
            )
    if gate == "P6":
        review_value = values.get("review_version", "")
        if re.fullmatch(r"[1-9][0-9]{0,8}", review_value) is None:
            raise ValueError("SESSION review_version must be a positive version approved at P5")
        require_review_evidence(project_dir, count, int(review_value))
    return values


def session_count(session: dict[str, str]) -> int:
    """Return the already-validated static count."""
    return int(session["count"])
