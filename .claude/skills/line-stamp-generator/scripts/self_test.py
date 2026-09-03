#!/usr/bin/env python3
from __future__ import annotations

from PIL import Image, ImageDraw

from image_utils import fill_small_transparent_holes, hidden_rgb_pixels, sanitize_alpha


def main() -> None:
    character = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(character)
    draw.rectangle((4, 4, 35, 35), fill=(20, 80, 40, 255))
    draw.rectangle((10, 10, 11, 11), fill=(0, 0, 0, 0))
    draw.rectangle((20, 20, 25, 25), fill=(0, 0, 0, 0))
    repaired = fill_small_transparent_holes(character, max_pixels=4)
    assert repaired.getpixel((10, 10))[3] == 255, "micro-hole was not repaired"
    assert repaired.getpixel((22, 22))[3] == 0, "deliberate negative space was incorrectly filled"

    text_like_ring = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(text_like_ring)
    ring_draw.ellipse((8, 8, 31, 31), fill=(255, 230, 120, 255))
    ring_draw.ellipse((15, 15, 24, 24), fill=(0, 0, 0, 0))
    cleaned = sanitize_alpha(text_like_ring)
    assert cleaned.getpixel((19, 19))[3] == 0, "final sanitation filled a text counter"

    dirty = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    dirty.putpixel((0, 0), (255, 255, 255, 5))
    clean = sanitize_alpha(dirty, alpha_floor=12)
    assert clean.getpixel((0, 0)) == (0, 0, 0, 0), "low-alpha RGB was not cleared"
    assert hidden_rgb_pixels(clean) == 0
    print("PASS layer-isolation alpha-cleanup micro-hole-policy")


if __name__ == "__main__":
    main()
