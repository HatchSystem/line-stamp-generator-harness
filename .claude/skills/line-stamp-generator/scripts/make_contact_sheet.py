#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a dark-background, versioned review sheet")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="Use a versioned name such as review-v02.png")
    parser.add_argument("--cols", type=int, default=4)
    args = parser.parse_args()

    files = sorted(Path(args.input).glob("stamp*.png"))
    if not files:
        raise SystemExit("No stamp*.png files found")
    images = [Image.open(path).convert("RGBA") for path in files]
    cell_width = max(image.width for image in images)
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
        sheet.paste(image, (x + (cell_width - image.width) // 2, y), image)
        draw.text((x + 8, y + art_height + 5), path.stem, fill=(245, 245, 245), font=font)
        draw.rectangle(
            (x, y, x + cell_width - 1, y + art_height + label_height - 1),
            outline=(82, 88, 96),
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, optimize=True)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
