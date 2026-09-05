#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import stat
import zipfile
from pathlib import Path

from PIL import Image

from image_utils import (
    hidden_rgb_pixels,
    internal_hole_sizes,
    internal_hole_sizes_outside_mask,
)
from project_context import enforce_facade_project
from session_contract import (
    load_static_session,
    project_stamp_name,
    session_count,
    submission_stamp_name,
)


STATIC_COUNTS = {8, 16, 24, 32, 40}
MAX_PNG_BYTES = 1_000_000
MAX_ZIP_BYTES = 60_000_000
ALLOWED_PNG_MODES = {"RGB", "RGBA"}


def alpha_bbox(image: Image.Image, threshold: int = 12):
    return image.convert("RGBA").getchannel("A").point(lambda p: 255 if p >= threshold else 0).getbbox()


def dpi_is_at_least_72(value: object) -> bool:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return False
    try:
        return float(value[0]) >= 72.0 and float(value[1]) >= 72.0
    except (TypeError, ValueError):
        return False


def has_exterior_transparent_background(image: Image.Image) -> bool:
    """Require a meaningful fully transparent outside region connecting all corners."""
    alpha = image.convert("RGBA").getchannel("A")
    width, height = alpha.size
    corners = {(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)}
    if any(alpha.getpixel(point) != 0 for point in corners):
        return False
    frontier = [(0, 0)]
    visited = {(0, 0)}
    while frontier:
        x, y = frontier.pop()
        for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            px, py = point
            if (
                0 <= px < width
                and 0 <= py < height
                and point not in visited
                and alpha.getpixel(point) == 0
            ):
                visited.add(point)
                frontier.append(point)
    return corners.issubset(visited) and len(visited) * 10 >= width * height


def validate_png(
    path: Path,
    exact_size: tuple[int, int] | None,
    min_size: tuple[int, int] | None,
    max_size: tuple[int, int] | None,
    min_margin: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if path.is_symlink() or not path.is_file():
        errors.append(f"missing {path.name}")
        return
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        errors.append(f"cannot stat {path.name}: {exc}")
        return
    if file_size > MAX_PNG_BYTES:
        errors.append(f"{path.name} exceeds 1MB")
    try:
        with Image.open(path) as opened:
            frame_count = getattr(opened, "n_frames", 1)
            animated = bool(getattr(opened, "is_animated", False))
            opened.load()
            image_format = opened.format
            image_mode = opened.mode
            image_dpi = opened.info.get("dpi")
            image = opened.copy()
    except Exception as exc:
        errors.append(f"{path.name} is not a readable image: {exc}")
        return
    if image_format != "PNG":
        errors.append(f"{path.name} format is {image_format}, expected PNG")
    if animated or frame_count != 1:
        errors.append(f"{path.name} is animated or multi-frame ({frame_count} frames); static PNG required")
    if image_mode not in ALLOWED_PNG_MODES:
        errors.append(
            f"{path.name} mode is {image_mode}, expected original PNG mode RGB or RGBA"
        )
    if not dpi_is_at_least_72(image_dpi):
        errors.append(f"{path.name} has no 72dpi-or-higher PNG resolution metadata: {image_dpi!r}")
    if exact_size and image.size != exact_size:
        errors.append(f"{path.name} size {image.size} != {exact_size}")
    if min_size and (image.width < min_size[0] or image.height < min_size[1]):
        errors.append(f"{path.name} size {image.size} is below {min_size}")
    if max_size and (image.width > max_size[0] or image.height > max_size[1]):
        errors.append(f"{path.name} size {image.size} exceeds {max_size}")
    if image.width % 2 or image.height % 2:
        errors.append(f"{path.name} has odd dimensions {image.size}")
    rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] != 0:
        errors.append(f"{path.name} has no fully transparent background")
    elif not has_exterior_transparent_background(rgba):
        errors.append(
            f"{path.name} has no connected exterior transparent background reaching all corners"
        )
    leaks = hidden_rgb_pixels(rgba)
    if leaks:
        errors.append(f"{path.name} has {leaks} hidden RGB pixels below alpha threshold")
    bbox = alpha_bbox(rgba)
    if bbox is None:
        errors.append(f"{path.name} has no visible content")
    else:
        left, top, right, bottom = bbox
        margins = (left, top, rgba.width - right, rgba.height - bottom)
        if min(margins) < min_margin:
            errors.append(f"{path.name} content margin {margins} is below required {min_margin}px")
        elif min_margin >= 12 and min(margins) < 16:
            warnings.append(
                f"{path.name} content margin {margins} passes 12px minimum but is below 16px target"
            )


def validate_zip(
    zip_path: Path,
    root: Path,
    expected_names: list[str],
    errors: list[str],
) -> None:
    if zip_path.is_symlink() or not zip_path.is_file():
        errors.append(f"missing ZIP {zip_path}")
        return
    try:
        zip_size = zip_path.stat().st_size
    except OSError as exc:
        errors.append(f"cannot stat ZIP {zip_path}: {exc}")
        return
    if zip_size > MAX_ZIP_BYTES:
        errors.append(f"ZIP exceeds 60MB: {zip_size}B")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            names = sorted(info.filename for info in infos)
            expected_zip = sorted(expected_names)
            if names != expected_zip:
                errors.append(f"ZIP members differ: expected={expected_zip} found={names}")

            info_by_name: dict[str, list[zipfile.ZipInfo]] = {}
            for info in infos:
                info_by_name.setdefault(info.filename, []).append(info)
            for name in expected_names:
                matches = info_by_name.get(name, [])
                if len(matches) != 1:
                    continue
                info = matches[0]
                if info.is_dir() or info.external_attr & 0x10:
                    errors.append(f"ZIP member {name} is a directory")
                    continue
                file_type = stat.S_IFMT(info.external_attr >> 16)
                if file_type not in {0, stat.S_IFREG}:
                    errors.append(f"ZIP member {name} is not a regular file")
                    continue
                local_path = root / name
                if local_path.is_symlink() or not local_path.is_file():
                    errors.append(f"cannot compare ZIP member {name}: local file is missing")
                    continue
                try:
                    local_size = local_path.stat().st_size
                except OSError as exc:
                    errors.append(f"cannot stat {name} for ZIP comparison: {exc}")
                    continue
                if info.file_size > MAX_PNG_BYTES:
                    errors.append(f"ZIP member {name} exceeds 1MB uncompressed")
                    continue
                if local_size > MAX_PNG_BYTES:
                    errors.append(f"cannot compare ZIP member {name}: local file exceeds 1MB")
                    continue
                try:
                    archived_bytes = archive.read(info)
                    local_bytes = local_path.read_bytes()
                except Exception as exc:
                    errors.append(f"cannot read ZIP member {name}: {exc}")
                    continue
                if archived_bytes != local_bytes:
                    errors.append(f"ZIP member {name} differs from {local_path}")
    except Exception as exc:
        errors.append(f"ZIP is not readable: {zip_path}: {exc}")


def validate_stamp_sources(
    project_dir: Path,
    submit_dir: Path,
    count: int,
    errors: list[str],
) -> None:
    """Bind every submitted stamp byte-for-byte to its reviewed project source."""
    source_dir = project_dir / "stamps"
    if source_dir.is_symlink() or not source_dir.is_dir():
        errors.append("cannot bind submitted stamps: project stamps/ is missing or indirect")
        return
    for index in range(1, count + 1):
        source_name = project_stamp_name(index)
        submitted_name = submission_stamp_name(index)
        source = source_dir / source_name
        submitted = submit_dir / submitted_name
        if source.is_symlink() or not source.is_file():
            errors.append(
                f"cannot bind submitted {submitted_name}: reviewed source "
                f"stamps/{source_name} is missing or indirect"
            )
            continue
        if submitted.is_symlink() or not submitted.is_file():
            continue  # validate_png reports the missing submitted file.
        try:
            source_bytes = source.read_bytes()
            submitted_bytes = submitted.read_bytes()
        except OSError as exc:
            errors.append(
                f"cannot compare submitted {submitted_name} with reviewed "
                f"stamps/{source_name}: {exc}"
            )
            continue
        if submitted_bytes != source_bytes:
            errors.append(
                f"submitted {submitted_name} differs from reviewed stamps/{source_name}"
            )


def validate_submission_names(
    root: Path,
    count: int,
    errors: list[str],
    warnings: list[str],
) -> list[str]:
    """Validate Creators Market names and report legacy outputs without deleting them."""
    expected_names = [submission_stamp_name(index) for index in range(1, count + 1)]
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        errors.append(f"cannot list submit directory for stamp names: {exc}")
        return expected_names
    found_names = sorted(
        path.name
        for path in entries
        if path.is_file()
        and re.fullmatch(r"[0-9]{2}\.png", path.name, flags=re.IGNORECASE)
    )
    if found_names != expected_names:
        errors.append(f"stamp names differ: expected={expected_names} found={found_names}")
    legacy_names = sorted(
        path.name
        for path in entries
        if (path.is_file() or path.is_symlink())
        and re.fullmatch(r"stamp[0-9]{2}\.png", path.name, flags=re.IGNORECASE)
    )
    if legacy_names:
        warnings.append(
            "legacy submit files are preserved but excluded from ZIP: "
            + ", ".join(legacy_names)
        )
    return expected_names


def checked_project_paths(
    root_value: str,
    character_value: str,
    zip_value: str,
    errors: list[str],
) -> tuple[Path, Path, Path]:
    """Bind validation evidence to the currently active project."""
    raw_root = Path(root_value)
    raw_character = Path(character_value)
    raw_zip = Path(zip_value)
    for label, path in (
        ("submit directory", raw_root),
        ("character-layer directory", raw_character),
        ("ZIP", raw_zip),
    ):
        if path.is_symlink():
            errors.append(f"{label} must not be a symlink: {path}")
    try:
        root = raw_root.resolve()
        character_dir = raw_character.resolve()
        zip_path = raw_zip.resolve()
    except OSError as exc:
        errors.append(f"cannot resolve validation paths: {exc}")
        return raw_root, raw_character, raw_zip
    project_dir = root.parent
    try:
        enforce_facade_project(project_dir, "validation")
    except ValueError as exc:
        errors.append(str(exc))
    if root != project_dir / "submit":
        errors.append("--dir must be the active project's submit/ directory")
    if character_dir != project_dir / "character-layers":
        errors.append("--character-dir must be the same project's character-layers/ directory")
    if zip_path.parent != root or zip_path.suffix.casefold() != ".zip":
        errors.append("--zip must be a .zip file directly inside the same submit/ directory")
    if project_dir.parent.name != "projects" or raw_root.parent.is_symlink():
        errors.append("validation paths must belong to projects/<slug>/")
    active_path = project_dir.parent / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        errors.append("projects/ACTIVE must be a regular non-symlink file during validation")
    else:
        try:
            active = active_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read projects/ACTIVE as UTF-8: {exc}")
        else:
            if active != project_dir.name:
                errors.append(
                    f"projects/ACTIVE={active!r} does not select validation project {project_dir.name!r}"
                )
    return root, character_dir, zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a static LINE sticker submit folder without mistaking text counters for cutout leaks")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--character-dir", required=True, help="Character-only layers from the same project")
    parser.add_argument("--max-micro-hole", type=int, default=64)
    parser.add_argument("--min-margin", type=int, default=12)
    parser.add_argument("--text-mode", choices=("font", "ai", "none"), default="font", help="ai: versioned text masks exclude glyph counters from hole checks")
    parser.add_argument("--zip", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    root, character_dir, zip_path = checked_project_paths(
        args.dir, args.character_dir, args.zip, errors
    )
    if errors:
        print(f"stamps=0 errors={len(errors)} warnings=0")
        for message in errors:
            print("ERROR", message)
        raise SystemExit(1)
    if args.count not in STATIC_COUNTS:
        print("stamps=0 errors=1 warnings=0")
        print(f"ERROR count {args.count} is not allowed for static stickers {sorted(STATIC_COUNTS)}")
        raise SystemExit(1)
    session: dict[str, str] = {}
    try:
        session = load_static_session(root.parent, {"P6"})
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if args.count != session_count(session):
            errors.append(f"--count {args.count} differs from SESSION count {session['count']}")
        if args.text_mode != session["text_mode"]:
            errors.append(
                f"--text-mode {args.text_mode!r} differs from SESSION "
                f"text_mode={session['text_mode']!r}"
            )
    if args.max_micro_hole < 0:
        errors.append("hole threshold must be nonnegative")
    if args.min_margin not in range(12, 17):
        errors.append("--min-margin must be from 12 through 16 pixels")

    expected_names = validate_submission_names(root, args.count, errors, warnings)

    validate_png(root / "main.png", (240, 240), None, None, 0, errors, warnings)
    validate_png(root / "tab.png", (96, 74), None, None, 0, errors, warnings)
    stamp_minimum = (80, 80)
    stamp_limit = (370, 320)
    for name in expected_names:
        path = root / name
        validate_png(path, None, stamp_minimum, stamp_limit, args.min_margin, errors, warnings)
    validate_stamp_sources(root.parent, root, args.count, errors)

    if args.text_mode == "ai":
        mask_value = session.get("text_mask_version", "")
        if re.fullmatch(r"[1-9][0-9]{0,8}", mask_value) is None:
            errors.append("AI micro-hole check requires positive SESSION text_mask_version")
        else:
            mask_dir = root.parent / "text-masks" / f"v{int(mask_value):02d}"
            if mask_dir.is_symlink() or not mask_dir.is_dir():
                errors.append("AI micro-hole check requires a regular versioned text-mask directory")
            else:
                for index, name in enumerate(expected_names, start=1):
                    source = root / name
                    mask_path = mask_dir / project_stamp_name(index)
                    if mask_path.is_symlink() or not mask_path.is_file():
                        errors.append(f"missing text mask {mask_path}")
                        continue
                    try:
                        with Image.open(source) as opened:
                            opened.load()
                            stamp = opened.convert("RGBA")
                        with Image.open(mask_path) as opened_mask:
                            opened_mask.load()
                            mask = opened_mask.convert("L")
                        micro_holes = [
                            size
                            for size in internal_hole_sizes_outside_mask(stamp, mask)
                            if size <= args.max_micro_hole
                        ]
                    except Exception as exc:
                        errors.append(f"cannot apply {mask_path.name} to {name}: {exc}")
                        continue
                    if micro_holes:
                        errors.append(
                            f"{name} has non-text micro-hole sizes {micro_holes[:8]}"
                        )
    else:
        for index, name in enumerate(expected_names, start=1):
            source = character_dir / project_stamp_name(index)
            if source.is_symlink() or not source.is_file():
                errors.append(f"missing character layer {source}")
                continue
            try:
                with Image.open(source) as opened:
                    opened.load()
                    character = opened.convert("RGBA")
            except Exception as exc:
                errors.append(f"character layer {source} is not a readable image: {exc}")
                continue
            micro_holes = [
                size for size in internal_hole_sizes(character) if size <= args.max_micro_hole
            ]
            if micro_holes:
                errors.append(
                    f"{source.name} character layer has micro-hole sizes {micro_holes[:8]}"
                )

    validate_zip(zip_path, root, ["main.png", "tab.png", *expected_names], errors)

    print(f"stamps={len(expected_names)} errors={len(errors)} warnings={len(warnings)}")
    for message in errors:
        print("ERROR", message)
    for message in warnings:
        print("WARN", message)
    if errors:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
