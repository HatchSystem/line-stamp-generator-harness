#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def process(
    source: Path,
    remove_light_background: bool,
    light_min: int,
    chroma_max: int,
    max_hole_pixels: int,
    outline: int,
    alpha_floor: int,
):
    image = Image.open(source).convert("RGBA")
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
    parser.add_argument("--no-fill-holes", action="store_true", help="text_mode=ai: 文字のカウンターを埋めないため穴補正を行わない")
    parser.add_argument("--outline", type=int, default=10)
    parser.add_argument("--alpha-floor", type=int, default=12)
    args = parser.parse_args()
    output = process(
        Path(args.src),
        args.remove_light_background,
        args.light_min,
        args.chroma_max,
        0 if args.no_fill_holes else args.max_hole_pixels,
        args.outline,
        args.alpha_floor,
    )
    destination = Path(args.dst)
    save_png(output, destination)
    print(f"wrote {destination} {output.size} {destination.stat().st_size}B")


if __name__ == "__main__":
    main()
