#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from project_context import enforce_facade_project
from session_contract import load_static_session, read_regular_bytes, session_count
from transaction_utils import exclusive_lock


REVIEW_NAME_RE = re.compile(r"review-v([0-9]{2,})\.png")
REVIEW_ARTIFACT_RE = re.compile(r"review-v([0-9]{2,})\.(?:json|png)")


def expected_review_inputs(project_dir: Path) -> list[str]:
    """Return the exact P5 stamp filenames declared by the active SESSION."""
    session = load_static_session(project_dir, {"P5"})
    return [f"stamp{index:02d}.png" for index in range(1, session_count(session) + 1)]


def checked_stamp_files(input_dir: Path, expected_names: list[str]) -> list[Path]:
    """Reject missing, extra, non-canonical, or non-regular stamp-like inputs."""
    try:
        stamp_like = [
            path
            for path in input_dir.iterdir()
            if path.name.casefold().startswith("stamp") and path.suffix.casefold() == ".png"
        ]
    except OSError as exc:
        raise ValueError(f"cannot list review inputs: {exc}") from exc
    actual_names = sorted(path.name for path in stamp_like)
    if actual_names != expected_names:
        raise ValueError(
            "review requires exactly the canonical SESSION stamp set; "
            f"expected={expected_names} found={actual_names}"
        )
    files = [input_dir / name for name in expected_names]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError("review inputs must be regular non-symlink PNG files")
    return files


def checked_paths(input_value: str, output_value: str) -> tuple[Path, Path]:
    """Bind an unused versioned review artifact to the input stamp project."""
    input_dir = Path(input_value)
    output = Path(output_value)
    name_match = REVIEW_NAME_RE.fullmatch(output.name)
    if name_match is None:
        raise ValueError("output filename must be versioned as review-vNN.png")
    requested_version = int(name_match.group(1))
    if requested_version <= 0:
        raise ValueError("review versions start at v01")
    if output.name != f"review-v{requested_version:02d}.png":
        raise ValueError("review filename must use canonical zero-padded version syntax")
    evidence_output = output.with_suffix(".json")
    if output.exists() or output.is_symlink() or evidence_output.exists() or evidence_output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing review artifact pair: {output.stem}")
    if input_dir.is_symlink() or not input_dir.is_dir():
        raise ValueError("--input must be a regular project stamps/ directory")
    if input_dir.parent.is_symlink() or output.parent.is_symlink():
        raise ValueError("project and review directories must not be symlinks")
    raw_project = input_dir.parent
    enforce_facade_project(raw_project, "review")
    projects_dir = raw_project.parent
    if projects_dir.name != "projects":
        raise ValueError("review paths must belong to projects/<slug>/")
    active_path = projects_dir / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file during review")
    try:
        active = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read projects/ACTIVE as UTF-8: {exc}") from exc
    if active != raw_project.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select review project {raw_project.name!r}"
        )
    resolved_input = input_dir.resolve()
    project_dir = resolved_input.parent
    if resolved_input != project_dir / "stamps":
        raise ValueError("--input must be the project's stamps/ directory")
    if output.parent.resolve() != project_dir / "review":
        raise ValueError("--output must be inside the same project's review/ directory")
    existing_versions = [
        int(match.group(1))
        for path in output.parent.glob("review-v*.*")
        if (match := REVIEW_ARTIFACT_RE.fullmatch(path.name))
    ]
    expected_version = max(existing_versions, default=0) + 1
    if requested_version != expected_version:
        raise ValueError(
            f"next review artifact must be review-v{expected_version:02d}.png, "
            f"not {output.name}"
        )
    return resolved_input, output.parent.resolve() / output.name


def write_review_pair(output: Path, image_payload: bytes, evidence_payload: bytes) -> None:
    """Create the append-only PNG/JSON pair and remove only files created by this call on failure."""
    created: list[tuple[Path, os.stat_result]] = []
    try:
        for path, payload in (
            (output, image_payload),
            (output.with_suffix(".json"), evidence_payload),
        ):
            with path.open("xb") as destination:
                identity = os.fstat(destination.fileno())
                created.append((path, identity))
                written = destination.write(payload)
                if written != len(payload):
                    raise OSError(f"short write for review artifact: {written}/{len(payload)} bytes")
    except BaseException:
        for path, identity in reversed(created):
            try:
                current = path.stat(follow_symlinks=False)
            except (FileNotFoundError, OSError):
                continue
            if not path.is_symlink() and os.path.samestat(identity, current):
                path.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a light/dark, versioned review sheet")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="Use a versioned name such as review-v02.png")
    parser.add_argument("--cols", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.cols <= 40:
        raise ValueError("--cols must be from 1 through 40")

    input_dir, output = checked_paths(args.input, args.output)
    session = load_static_session(input_dir.parent, {"P5"})
    expected_names = [
        f"stamp{index:02d}.png" for index in range(1, session_count(session) + 1)
    ]
    files = checked_stamp_files(input_dir, expected_names)
    if args.cols > len(files):
        raise ValueError("--cols must not exceed the SESSION stamp count")
    images = []
    stamp_hashes: list[str] = []
    for path in files:
        source_payload = read_regular_bytes(path)
        stamp_hashes.append(hashlib.sha256(source_payload).hexdigest())
        with Image.open(io.BytesIO(source_payload)) as opened:
            opened.load()
            images.append(opened.convert("RGBA"))
    preview_width = max(image.width for image in images)
    cell_width = preview_width * 2
    art_height = max(image.height for image in images)
    label_height = 26
    rows = math.ceil(len(images) / args.cols)
    sheet = Image.new("RGB", (cell_width * args.cols, (art_height + label_height) * rows), (42, 46, 52))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for position, (path, image) in enumerate(zip(files, images)):
        column = position % args.cols
        row = position // args.cols
        x = column * cell_width
        y = row * (art_height + label_height)
        for preview_index, background in enumerate(((250, 250, 250), (42, 46, 52))):
            preview_x = x + preview_index * preview_width
            draw.rectangle(
                (preview_x, y, preview_x + preview_width - 1, y + art_height - 1),
                fill=background,
            )
            image_x = preview_x + (preview_width - image.width) // 2
            image_y = y + (art_height - image.height) // 2
            sheet.paste(image, (image_x, image_y), image)
        draw.text(
            (x + 8, y + art_height + 5),
            f"{path.stem} | light / dark",
            fill=(245, 245, 245),
            font=font,
        )
        draw.line((x + preview_width, y, x + preview_width, y + art_height - 1), fill=(120, 124, 130))
        draw.rectangle(
            (x, y, x + cell_width - 1, y + art_height + label_height - 1),
            outline=(82, 88, 96),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    # Render completely before reserving the final name. Exclusive creation makes
    # the append-only guarantee hold when agents race for the same version.
    encoded = io.BytesIO()
    sheet.save(encoded, format="PNG", optimize=True)
    payload = encoded.getvalue()
    version_match = REVIEW_NAME_RE.fullmatch(output.name)
    if version_match is None:
        raise ValueError("internal review filename validation failed")
    version = int(version_match.group(1))
    evidence = {
        "schema_version": 1,
        "version": version,
        "project": input_dir.parent.name,
        "gate": "P5",
        "presentation": "all-stamps-light-dark",
        "session_count": session_count(session),
        "review_file": output.name,
        "review_sha256": hashlib.sha256(payload).hexdigest(),
        "stamps": [
            {
                "id": index,
                "file": path.name,
                "sha256": stamp_hash,
            }
            for index, (path, stamp_hash) in enumerate(
                zip(files, stamp_hashes), start=1
            )
        ],
    }
    evidence_payload = (
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    with exclusive_lock(output.parent / ".line-stamp-review.lock", "review evidence transaction"):
        write_review_pair(output, payload, evidence_payload)
    print(f"wrote {output} and {output.with_suffix('.json')}")


if __name__ == "__main__":
    main()
