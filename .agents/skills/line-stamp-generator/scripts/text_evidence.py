"""Record AI visual text checks and versioned text-region masks."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

from metadata_utils import loads_no_duplicates
from project_context import enforce_facade_project
from session_contract import load_static_session, read_regular_bytes, visual_text_matches
from transaction_utils import exclusive_lock

def checked_project_paths(
    manifest_value: str, stamp_value: str, review_value: str
) -> tuple[Path, Path, Path]:
    raw_manifest = Path(manifest_value)
    raw_stamps = Path(stamp_value)
    raw_review = Path(review_value)
    if raw_manifest.is_symlink() or not raw_manifest.is_file():
        raise ValueError("--manifest must be a regular non-symlink project manifest.json")
    if raw_manifest.name != "manifest.json" or raw_manifest.parent.is_symlink():
        raise ValueError("--manifest must be projects/<slug>/manifest.json")
    for label, path in (("--dir", raw_stamps), ("--review-dir", raw_review)):
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
    project_dir = raw_manifest.parent.resolve()
    enforce_facade_project(project_dir, "text verification")
    manifest = raw_manifest.resolve()
    stamps = raw_stamps.resolve()
    review = raw_review.resolve()
    if stamps != project_dir / "stamps":
        raise ValueError("--dir must be the same project's stamps/ directory")
    if review != project_dir / "review":
        raise ValueError("--review-dir must be the same project's review/ directory")
    if project_dir.parent.name != "projects":
        raise ValueError("verify-text paths must belong to projects/<slug>/")
    active_path = project_dir.parent / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file")
    active = active_path.read_text(encoding="utf-8").strip()
    if active != project_dir.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select project {project_dir.name!r}"
        )
    return manifest, stamps, review


def next_version(review_dir: Path) -> int:
    versions = [
        int(match.group(1))
        for path in review_dir.glob("text-check-v*.*")
        if (match := re.fullmatch(r"text-check-v(\d+)\.(?:md|json)", path.name))
    ]
    return max(versions, default=0) + 1


def verification_session(project_dir: Path) -> tuple[dict[str, str], list[str]]:
    try:
        values = load_static_session(project_dir, {"P4", "P5"})
    except ValueError as exc:
        return {}, [str(exc)]
    errors = []
    if values.get("text") != "yes" or values.get("text_mode") != "ai":
        errors.append("verify-text requires SESSION text=yes and text_mode=ai")
    return values, errors


def verification_scope(
    session: dict[str, str], manifest_ids: set[int], requested_ids: set[int] | None
) -> set[int]:
    count = int(session["count"])
    expected_ids = set(range(1, count + 1))
    extra = sorted(manifest_ids - expected_ids)
    if extra:
        raise ValueError(f"manifest ids exceed SESSION count: {extra}")
    if session["gate"] == "P4":
        if requested_ids != {1} or 1 not in manifest_ids:
            raise ValueError("P4 requires --only 1 and a manifest item for stamp01")
        return {1}
    if manifest_ids != expected_ids:
        raise ValueError(
            "P5 requires manifest ids exactly 1..SESSION count; "
            f"missing={sorted(expected_ids - manifest_ids)} extra={extra}"
        )
    if requested_ids is not None:
        raise ValueError("P5 final evidence must recheck every id; omit --only")
    return expected_ids


def parse_requested_ids(value: str | None, manifest_ids: set[int]) -> set[int] | None:
    if value is None:
        return None
    tokens = [part.strip() for part in value.split(",")]
    if not tokens or any(not token for token in tokens):
        raise ValueError("--only requires comma-separated stamp ids")
    try:
        ids = [int(token) for token in tokens]
    except ValueError as exc:
        raise ValueError("--only stamp ids must be integers") from exc
    if any(item_id not in range(1, 41) for item_id in ids):
        raise ValueError("--only stamp ids must be from 1 through 40")
    if len(ids) != len(set(ids)):
        raise ValueError("--only must not contain duplicate ids")
    absent = sorted(set(ids) - manifest_ids)
    if absent:
        raise ValueError(f"--only ids are missing from manifest: {absent}")
    return set(ids)


def expected_text(item: dict, position: int) -> str:
    value = item.get("text")
    if isinstance(value, str):
        result = value
    elif isinstance(value, list) and value and all(isinstance(line, str) for line in value):
        result = "".join(value)
    else:
        raise ValueError(f"manifest.items[{position}].text must be a string or string list")
    if not result.strip():
        raise ValueError(f"manifest.items[{position}].text must not be empty")
    return result


def text_region(item: dict, size: tuple[int, int], position: int) -> tuple[int, int, int, int]:
    """Validate the tight text-only rectangle used to protect glyph counters."""
    value = item.get("text_region")
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(number) is not int for number in value)
    ):
        raise ValueError(
            f"manifest.items[{position}].text_region must be [left, top, right, bottom] integers"
        )
    left, top, right, bottom = value
    width, height = size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(
            f"manifest.items[{position}].text_region is outside the {width}x{height} stamp"
        )
    if (right - left) * (bottom - top) > width * height * 0.6:
        raise ValueError(
            f"manifest.items[{position}].text_region covers over 60% of the stamp; "
            "use a tight text-only region"
        )
    return left, top, right, bottom


def mask_payload(size: tuple[int, int], region: tuple[int, int, int, int]) -> bytes:
    mask = Image.new("L", size, 0)
    left, top, right, bottom = region
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    output = io.BytesIO()
    mask.save(output, format="PNG", optimize=False)
    return output.getvalue()


def load_visual_review(
    value: str,
    project_dir: Path,
    manifest_sha256: str,
    selected_ids: set[int],
) -> dict[int, dict]:
    """Read AI observations; this function does not recognize images."""
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("--visual-review must be a regular non-symlink JSON file")
    resolved = path.resolve()
    allowed = ((project_dir / "review").resolve(), (project_dir / "meta").resolve())
    if not resolved.is_relative_to(project_dir.resolve()) or not any(
        resolved.is_relative_to(root) for root in allowed
    ):
        raise ValueError("--visual-review must stay under the active project review/ or meta/")
    payload = loads_no_duplicates(read_regular_bytes(resolved).decode("utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("method") != "ai-visual"
    ):
        raise ValueError("visual review requires schema_version 1 and method ai-visual")
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError("visual review does not match current manifest.json")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("visual review items must be an array")
    by_id: dict[int, dict] = {}
    for row in items:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError("visual review contains an invalid item")
        row_id = row["id"]
        if row_id in by_id:
            raise ValueError(f"visual review duplicates id {row_id}")
        status = row.get("status")
        if not isinstance(status, str) or status not in {
            "match", "mismatch", "unreadable", "not-run"
        } or not isinstance(row.get("recognized"), str):
            raise ValueError(f"visual review requires recognized text and status for id {row_id}")
        by_id[row_id] = row
    if set(by_id) != selected_ids:
        raise ValueError("visual review ids do not match the requested scope")
    return by_id


def write_new_files(entries: list[tuple[Path, bytes]]) -> None:
    created: list[tuple[Path, os.stat_result]] = []
    try:
        for path, payload in entries:
            with path.open("xb") as destination:
                identity = os.fstat(destination.fileno())
                created.append((path, identity))
                written = destination.write(payload)
                if written != len(payload):
                    raise OSError(f"short write for {path}: {written}/{len(payload)} bytes")
    except BaseException:
        for path, identity in reversed(created):
            try:
                current = path.stat(follow_symlinks=False)
            except (FileNotFoundError, OSError):
                current = None
            if current is not None and not path.is_symlink() and os.path.samestat(identity, current):
                path.unlink()
        raise


def build_rows(
    manifest_items: list,
    selected_ids: set[int],
    stamp_dir: Path,
    visual_rows: dict[int, dict],
) -> tuple[list[dict], dict[int, bytes]]:
    rows: list[dict] = []
    masks: dict[int, bytes] = {}
    for position, item in enumerate(manifest_items, start=1):
        index = int(item["id"])
        if index not in selected_ids:
            continue
        path = stamp_dir / f"stamp{index:02d}.png"
        row: dict = {
            "id": index,
            "file": path.name,
            "sha256": None,
            "expected": "",
            "recognized": "",
            "status": "",
            "text_region": item.get("text_region"),
            "mask_file": None,
            "mask_sha256": None,
        }
        try:
            expected = expected_text(item, position)
            row["expected"] = expected
            stamp_payload = read_regular_bytes(path)
            row["sha256"] = hashlib.sha256(stamp_payload).hexdigest()
            with Image.open(io.BytesIO(stamp_payload)) as opened:
                opened.load()
                image = opened.convert("RGBA")
            region = text_region(item, image.size, position)
            row["text_region"] = list(region)
            masks[index] = mask_payload(image.size, region)
            observation = visual_rows[index]
            if (
                observation.get("file") != path.name
                or observation.get("sha256") != row["sha256"]
                or observation.get("expected") != expected
            ):
                raise ValueError(f"visual review does not match current {path.name}")
            row["recognized"] = observation["recognized"]
            row["status"] = observation["status"]
            if row["status"] == "match" and not visual_text_matches(expected, row["recognized"]):
                row["status"] = "mismatch"
        except (OSError, ValueError, RuntimeError) as exc:
            row["status"] = "unreadable"
            row["error"] = str(exc)
        rows.append(row)
    return rows, masks


def markdown_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    ).replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Record AI visual observations and text masks (does not recognize images)"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dir", required=True, help="same project's stamps/ directory")
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--only", help="P4 only: comma-separated stamp ids")
    parser.add_argument(
        "--visual-review", required=True,
        help="JSON observations recorded by the AI after opening each final image",
    )
    args = parser.parse_args()

    try:
        manifest_path, stamp_dir, review_dir = checked_project_paths(
            args.manifest, args.dir, args.review_dir
        )
        session, session_errors = verification_session(manifest_path.parent)
        if session_errors:
            raise ValueError("; ".join(session_errors))
        manifest_payload = read_regular_bytes(manifest_path)
        manifest = loads_no_duplicates(manifest_payload.decode("utf-8"))
        manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
        if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
            raise ValueError("manifest root must contain an items array")
        items_by_id: dict[int, dict] = {}
        for position, item in enumerate(manifest["items"], start=1):
            if not isinstance(item, dict) or type(item.get("id")) is not int:
                raise ValueError(f"manifest.items[{position}] requires an integer id")
            item_id = item["id"]
            if item_id not in range(1, 41) or item_id in items_by_id:
                raise ValueError(f"manifest.items[{position}].id is invalid or duplicated")
            items_by_id[item_id] = item
        requested = parse_requested_ids(args.only, set(items_by_id))
        selected_ids = verification_scope(session, set(items_by_id), requested)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR verify-text: {exc}")
        return 1

    try:
        visual_rows = load_visual_review(
            args.visual_review, manifest_path.parent, manifest_sha256, selected_ids
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR verify-text: invalid visual review: {exc}")
        return 1
    rows, masks = build_rows(manifest["items"], selected_ids, stamp_dir, visual_rows)
    try:
        if review_dir.exists() and not review_dir.is_dir():
            raise ValueError("review path must be a directory")
        review_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        print(f"ERROR verify-text: cannot prepare review directory: {exc}")
        return 1
    mask_root = manifest_path.parent / "text-masks"
    if mask_root.is_symlink() or (mask_root.exists() and not mask_root.is_dir()):
        print("ERROR verify-text: text-masks must be a regular non-symlink directory")
        return 1
    try:
        mask_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR verify-text: cannot prepare text-masks directory: {exc}")
        return 1
    try:
        with exclusive_lock(review_dir / ".line-stamp-verify.lock", "verify-text transaction"):
            version = next_version(review_dir)
            mask_dir = mask_root / f"v{version:02d}"
            if mask_dir.exists() or mask_dir.is_symlink():
                raise ValueError(f"versioned mask directory already exists: {mask_dir.name}")
            mask_dir.mkdir()
            try:
                entries: list[tuple[Path, bytes]] = []
                for row in rows:
                    if row["id"] not in masks:
                        continue
                    mask_name = f"stamp{row['id']:02d}.png"
                    payload = masks[row["id"]]
                    row["mask_file"] = f"text-masks/v{version:02d}/{mask_name}"
                    row["mask_sha256"] = hashlib.sha256(payload).hexdigest()
                    entries.append((mask_dir / mask_name, payload))
                scope = "sample" if session["gate"] == "P4" else "all"
                report = {
                    "schema_version": 3,
                    "version": version,
                    "project": manifest_path.parent.name,
                    "gate": session["gate"],
                    "scope": scope,
                    "session_count": int(session["count"]),
                    "manifest_sha256": manifest_sha256,
                    "method": "ai-visual",
                    "rows": rows,
                }
                lines = [
                    f"# text-check v{version:02d}", "",
                    f"- project: `{manifest_path.parent.name}`",
                    f"- gate: `{session['gate']}`", f"- scope: `{scope}`",
                    "- method: ai-visual (observations supplied by the AI)",
                    "- user approval: P4 adoption / P5 full review before SESSION text_check=ok", "",
                    "| id | expected | AI reading | status |",
                    "|---|---|---|---|",
                ]
                for row in rows:
                    expected = markdown_cell(row["expected"])
                    recognized = markdown_cell(row["recognized"])
                    lines.append(
                        f"| {row['id']:02d} | {expected} | {recognized} | {row['status']} |"
                    )
                    if row.get("error"):
                        lines.append(f"\n{row['id']:02d}: {markdown_cell(row['error'])}\n")
                lines.extend([
                    "", "The CLI records observations; it does not recognize or visually inspect images.",
                    "Only match on every image can satisfy P6 after P5 user approval.",
                    "Text masks exclude only declared text regions from micro-hole checks.", "",
                ])
                md_path = review_dir / f"text-check-v{version:02d}.md"
                json_path = review_dir / f"text-check-v{version:02d}.json"
                entries.extend([
                    (md_path, "\n".join(lines).encode("utf-8")),
                    (json_path, (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")),
                ])
                write_new_files(entries)
            except BaseException:
                if mask_dir.is_dir() and not mask_dir.is_symlink():
                    for child in mask_dir.iterdir():
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                    mask_dir.rmdir()
                raise
    except (OSError, ValueError) as exc:
        print(f"ERROR verify-text: could not write evidence: {exc}")
        return 1

    statuses = ("match", "mismatch", "unreadable", "not-run")
    counts = {status: sum(row["status"] == status for row in rows) for status in statuses}
    print(
        f"text-check v{version:02d}: checked={len(rows)} method=ai-visual "
        + " ".join(f"{key}={value}" for key, value in counts.items())
    )
    print(f"report: {md_path}")
    print(f"masks: {mask_dir}")
    return 0 if all(row["status"] == "match" for row in rows) else 1
