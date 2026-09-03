#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from image_utils import (
    add_white_outline,
    fill_small_transparent_holes,
    remove_edge_light_background,
    sanitize_alpha,
    save_png,
    trim_alpha,
)
from project_context import enforce_facade_project
from session_contract import load_static_session, session_count
from transaction_utils import ArtifactRollbackError, exclusive_lock, install_files_transaction


STAMP_NAME_RE = re.compile(r"stamp[0-9]{2}\.png")


def checked_paths(source_value: str, destination_value: str) -> tuple[Path, Path, Path]:
    """Bind preprocessing to raw/ -> characters/ inside the active project."""
    raw_source = Path(source_value)
    destination = Path(destination_value)
    if raw_source.is_symlink() or not raw_source.is_file():
        raise ValueError("src must be a regular non-symlink PNG in the active project's raw/")
    if destination.is_symlink():
        raise ValueError("dst must not be a symlink")
    if raw_source.name != destination.name or STAMP_NAME_RE.fullmatch(raw_source.name) is None:
        raise ValueError("src and dst must use the same stampNN.png filename")
    if raw_source.parent.is_symlink() or destination.parent.is_symlink():
        raise ValueError("raw and characters directories must not be symlinks")
    source = raw_source.resolve()
    project_dir = source.parent.parent
    enforce_facade_project(project_dir, "preprocess")
    if source.parent != project_dir / "raw":
        raise ValueError("src must be inside projects/<slug>/raw/")
    if destination.resolve() != project_dir / "characters" / source.name:
        raise ValueError("dst must be the same project's characters/stampNN.png")
    if project_dir.parent.name != "projects" or raw_source.parent.parent.is_symlink():
        raise ValueError("preprocess paths must belong to projects/<slug>/")
    active_path = project_dir.parent / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file during preprocessing")
    try:
        active = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read projects/ACTIVE as UTF-8: {exc}") from exc
    if active != project_dir.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select preprocess project {project_dir.name!r}"
        )
    return source, destination.resolve(), project_dir


def process(
    source: Path,
    remove_light_background: bool,
    light_min: int,
    chroma_max: int,
    max_hole_pixels: int,
    outline: int,
    alpha_floor: int,
):
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if remove_light_background:
        image = remove_edge_light_background(image, light_min, chroma_max)
    image = trim_alpha(image)
    if max_hole_pixels > 0:
        image = fill_small_transparent_holes(image, max_hole_pixels)
    image = add_white_outline(image, outline)
    return sanitize_alpha(trim_alpha(image), alpha_floor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare character-only PNGs before text composition")
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--remove-light-background", action="store_true")
    parser.add_argument("--light-min", type=int, default=228)
    parser.add_argument("--chroma-max", type=int, default=18)
    parser.add_argument("--max-hole-pixels", type=int, default=64)
    parser.add_argument(
        "--no-fill-holes",
        action="store_true",
        help="text_mode=ai: 文字のカウンターを保護するため穴補正を行わない（白縁も外周だけに付く）",
    )
    parser.add_argument("--outline", type=int, default=10)
    parser.add_argument("--alpha-floor", type=int, default=12)
    args = parser.parse_args()
    source, destination, project_dir = checked_paths(args.src, args.dst)
    session = load_static_session(project_dir, {"P4", "P5"})
    stamp_id = int(source.stem[5:7])
    if stamp_id not in range(1, session_count(session) + 1):
        raise ValueError(f"stamp id {stamp_id} exceeds SESSION count {session['count']}")
    if session["gate"] == "P4" and stamp_id != 1:
        raise ValueError("P4 preprocessing is limited to stamp01")
    if args.no_fill_holes != (session["text_mode"] == "ai"):
        raise ValueError(
            "--no-fill-holes is required exactly when SESSION text_mode=ai"
        )
    if not 0 <= args.light_min <= 255 or not 0 <= args.chroma_max <= 255:
        raise ValueError("light-min and chroma-max must be from 0 through 255")
    if args.max_hole_pixels < 0 or not 0 <= args.outline <= 64 or not 0 <= args.alpha_floor <= 255:
        raise ValueError("max-hole-pixels must be nonnegative, outline 0..64, and alpha-floor 0..255")
    output = process(
        source,
        args.remove_light_background,
        args.light_min,
        args.chroma_max,
        0 if args.no_fill_holes else args.max_hole_pixels,
        args.outline,
        args.alpha_floor,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    preserve_staging = False
    try:
        with exclusive_lock(project_dir / ".line-stamp-preprocess.lock", "preprocess-character transaction"):
            staging = Path(tempfile.mkdtemp(prefix=".line-stamp-preprocess-", dir=project_dir))
            staged = staging / destination.name
            save_png(output, staged)
            try:
                install_files_transaction(staging, [(staged, destination)])
            except ArtifactRollbackError:
                preserve_staging = True
                raise
    finally:
        if staging is not None and staging.exists() and not preserve_staging:
            shutil.rmtree(staging)
    print(f"wrote {destination} {output.size} {destination.stat().st_size}B")


if __name__ == "__main__":
    main()
