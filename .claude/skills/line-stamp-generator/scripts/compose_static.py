#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from image_utils import fill_small_transparent_holes, sanitize_alpha, save_png, trim_alpha


def color(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    if len(value) not in (6, 8):
        raise ValueError(f"Invalid color: {value}")
    channels = tuple(int(value[i : i + 2], 16) for i in range(0, len(value), 2))
    return (*channels, 255) if len(channels) == 3 else channels


def text_size(
    lines: list[str], font: ImageFont.FreeTypeFont, spacing: int, stroke_width: int
) -> tuple[int, int, tuple[int, int, int, int]]:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.multiline_textbbox(
        (0, 0), "\n".join(lines), font=font, spacing=spacing, align="center", stroke_width=stroke_width
    )
    return box[2] - box[0], box[3] - box[1], box


def choose_font(
    lines: list[str],
    font_path: Path,
    max_size: int,
    min_size: int,
    max_width: int,
    max_height: int,
    spacing: int,
    stroke_width: int,
) -> tuple[ImageFont.FreeTypeFont, tuple[int, int, int, int]]:
    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(str(font_path), size)
        width, height, box = text_size(lines, font, spacing, stroke_width)
        if width <= max_width and height <= max_height:
            return font, box
    raise ValueError(f"Text does not fit at minimum font size: {lines}")


def resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose transparent character layers with deterministic outlined text")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--character-layer-dir", required=True)
    parser.add_argument("--text-layer-dir")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    style = manifest["style"]
    if style.get("shadow"):
        raise ValueError("Text shadows are disabled; use a concentric outline only")
    text_mode = style.get("text_mode", "font")
    if text_mode not in ("font", "ai", "none"):
        raise ValueError("style.text_mode must be font, ai or none")
    draw_text = text_mode == "font"

    canvas_width, canvas_height = style.get("canvas", [370, 320])
    if canvas_width % 2 or canvas_height % 2:
        raise ValueError("Canvas dimensions must be even")
    text_zone = int(style.get("text_zone_height", 90)) if draw_text else 0
    margin = int(style.get("margin", 10))
    spacing = int(style.get("line_spacing", 4))
    stroke_width = int(style.get("outline_width", 5))
    font_path = resolve(base, style["font"]) if draw_text else None
    if draw_text and not font_path.exists():
        raise FileNotFoundError(font_path)

    outdir = Path(args.outdir)
    character_layer_dir = Path(args.character_layer_dir)
    text_layer_dir = Path(args.text_layer_dir) if args.text_layer_dir else None
    fill = color(style.get("text_fill", "#FFE57C"))
    outline = color(style.get("text_outline", "#084E2B"))
    alpha_floor = int(style.get("alpha_floor", 12))

    for item in manifest["items"]:
        index = int(item["id"])
        lines = item.get("text", [])
        if isinstance(lines, str):
            lines = lines.split("\n") if lines else []
        character = trim_alpha(Image.open(resolve(base, item["character"])).convert("RGBA"))
        character.thumbnail(
            (canvas_width - margin * 2, canvas_height - text_zone - margin),
            Image.Resampling.LANCZOS,
        )
        if draw_text:  # ai mode: text is baked into the character, never fill its counters
            character = fill_small_transparent_holes(
                character, max_pixels=int(style.get("max_hole_pixels_after_resize", 64))
            )
        character = sanitize_alpha(character, alpha_floor)

        character_layer = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        character_x = (canvas_width - character.width) // 2
        character_y = canvas_height - margin - character.height
        if character_y < text_zone:
            raise ValueError(f"Character overlaps text zone for item {index}")
        character_layer.alpha_composite(character, (character_x, character_y))

        text_layer = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        if lines and draw_text:
            font, box = choose_font(
                lines,
                font_path,
                int(style.get("max_font_size", 44)),
                int(style.get("min_font_size", 20)),
                canvas_width - margin * 2,
                text_zone - margin * 2,
                spacing,
                stroke_width,
            )
            width, height = box[2] - box[0], box[3] - box[1]
            x = (canvas_width - width) // 2 - box[0]
            y = margin + (text_zone - margin * 2 - height) // 2 - box[1]
            ImageDraw.Draw(text_layer).multiline_text(
                (x, y),
                "\n".join(lines),
                font=font,
                fill=fill,
                spacing=spacing,
                align="center",
                stroke_width=stroke_width,
                stroke_fill=outline,
            )

        final = Image.alpha_composite(character_layer, text_layer)
        final = sanitize_alpha(final, alpha_floor)
        name = f"stamp{index:02d}.png"
        save_png(final, outdir / name)
        save_png(sanitize_alpha(character_layer, alpha_floor), character_layer_dir / name)
        if text_layer_dir:
            save_png(sanitize_alpha(text_layer, alpha_floor), text_layer_dir / name)
        print(f"wrote {name} mode={text_mode} text={'/'.join(lines)}")


if __name__ == "__main__":
    main()
