#!/usr/bin/env python3
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from PIL import Image

from image_utils import hidden_rgb_pixels, internal_hole_sizes


STATIC_COUNTS = {8, 16, 24, 32, 40}


def alpha_bbox(image: Image.Image, threshold: int = 12):
    return image.convert("RGBA").getchannel("A").point(lambda p: 255 if p >= threshold else 0).getbbox()


def validate_png(
    path: Path,
    exact_size: tuple[int, int] | None,
    max_size: tuple[int, int] | None,
    min_margin: int,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not path.exists():
        errors.append(f"missing {path.name}")
        return
    if path.stat().st_size > 1_000_000:
        errors.append(f"{path.name} exceeds 1MB")
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        errors.append(f"{path.name} is not a readable image: {exc}")
        return
    if image.format != "PNG":
        errors.append(f"{path.name} format is {image.format}, expected PNG")
    if exact_size and image.size != exact_size:
        errors.append(f"{path.name} size {image.size} != {exact_size}")
    if max_size and (image.width > max_size[0] or image.height > max_size[1]):
        errors.append(f"{path.name} size {image.size} exceeds {max_size}")
    if image.width % 2 or image.height % 2:
        errors.append(f"{path.name} has odd dimensions {image.size}")
    rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] != 0:
        errors.append(f"{path.name} has no fully transparent background")
    leaks = hidden_rgb_pixels(rgba)
    if leaks:
        errors.append(f"{path.name} has {leaks} hidden RGB pixels below alpha threshold")
    bbox = alpha_bbox(rgba)
    if bbox:
        left, top, right, bottom = bbox
        margins = (left, top, rgba.width - right, rgba.height - bottom)
        if min(margins) < min_margin:
            warnings.append(f"{path.name} content margin {margins} is below {min_margin}px")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a static LINE sticker submit folder without mistaking text counters for cutout leaks")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--character-dir", help="Character-only layers used for accidental-hole checks")
    parser.add_argument("--text-zone-height", type=int, default=0, help="Fallback exclusion when character layers are unavailable")
    parser.add_argument("--max-micro-hole", type=int, default=64)
    parser.add_argument("--min-margin", type=int, default=8)
    parser.add_argument("--text-mode", choices=("font", "ai", "none"), default="font", help="ai: 文字が画像に焼き込まれているため穴検査をスキップし目視に委ねる")
    parser.add_argument("--zip")
    args = parser.parse_args()

    root = Path(args.dir)
    errors: list[str] = []
    warnings: list[str] = []
    if args.count not in STATIC_COUNTS:
        errors.append(f"count {args.count} is not allowed for static stickers {sorted(STATIC_COUNTS)}")

    expected_names = [f"stamp{index:02d}.png" for index in range(1, args.count + 1)]
    found_names = sorted(path.name for path in root.glob("stamp*.png"))
    if found_names != expected_names:
        errors.append(f"stamp names differ: expected={expected_names} found={found_names}")

    validate_png(root / "main.png", (240, 240), None, 0, errors, warnings)
    validate_png(root / "tab.png", (96, 74), None, 0, errors, warnings)
    stamp_limit = (370, 320)
    for name in expected_names:
        path = root / name
        validate_png(path, None, stamp_limit, args.min_margin, errors, warnings)

    character_dir = Path(args.character_dir) if args.character_dir else None
    if args.text_mode == "ai":
        warnings.append("text_mode=ai: micro-hole check skipped (text counters would be false positives); inspect review sheets on a dark background and run verify_text.py")
        expected_hole_names: list[str] = []
    else:
        expected_hole_names = expected_names
    for name in expected_hole_names:
        source = character_dir / name if character_dir else root / name
        if not source.exists():
            if character_dir:
                errors.append(f"missing character layer {source}")
            continue
        character = Image.open(source).convert("RGBA")
        if not character_dir and args.text_zone_height:
            character = character.crop((0, args.text_zone_height, character.width, character.height))
        micro_holes = [size for size in internal_hole_sizes(character) if size <= args.max_micro_hole]
        if micro_holes:
            errors.append(f"{name} character layer has micro-hole sizes {micro_holes[:8]}")

    if args.zip:
        zip_path = Path(args.zip)
        if not zip_path.exists():
            errors.append(f"missing ZIP {zip_path}")
        else:
            if zip_path.stat().st_size > 60_000_000:
                errors.append(f"ZIP exceeds 60MB: {zip_path.stat().st_size}B")
            with zipfile.ZipFile(zip_path) as archive:
                names = sorted(archive.namelist())
            expected_zip = sorted(["main.png", "tab.png", *expected_names])
            if names != expected_zip:
                errors.append(f"ZIP members differ: expected={expected_zip} found={names}")

    print(f"stamps={len(found_names)} errors={len(errors)} warnings={len(warnings)}")
    for message in errors:
        print("ERROR", message)
    for message in warnings:
        print("WARN", message)
    if errors:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
