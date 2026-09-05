from __future__ import annotations

import io
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def edge_connected(mask: np.ndarray) -> np.ndarray:
    """Return true pixels connected to a canvas edge using 4-connectivity."""
    height, width = mask.shape
    reached = np.zeros_like(mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        if mask[0, x]:
            queue.append((0, x))
        if mask[height - 1, x]:
            queue.append((height - 1, x))
    for y in range(height):
        if mask[y, 0]:
            queue.append((y, 0))
        if mask[y, width - 1]:
            queue.append((y, width - 1))
    while queue:
        y, x = queue.pop()
        if reached[y, x] or not mask[y, x]:
            continue
        reached[y, x] = True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not reached[ny, nx]:
                queue.append((ny, nx))
    return reached


def remove_edge_light_background(
    image: Image.Image, light_min: int = 228, chroma_max: int = 18
) -> Image.Image:
    """Remove only near-neutral light pixels connected to the image boundary."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[..., :3].astype(np.int16)
    light = rgb.min(axis=2) >= light_min
    neutral = (rgb.max(axis=2) - rgb.min(axis=2)) <= chroma_max
    outside = edge_connected(light & neutral)
    rgba[outside] = (0, 0, 0, 0)
    return Image.fromarray(rgba, "RGBA")


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    height, width = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        component: list[tuple[int, int]] = []
        queue = [(int(y), int(x))]
        seen[y, x] = True
        while queue:
            cy, cx = queue.pop()
            component.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        components.append(component)
    return components


def internal_hole_sizes(image: Image.Image, threshold: int = 16) -> list[int]:
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    transparent = alpha < threshold
    holes = transparent & ~edge_connected(transparent)
    return sorted((len(component) for component in _components(holes)), reverse=True)


def internal_hole_sizes_outside_mask(
    image: Image.Image,
    excluded_mask: Image.Image,
    threshold: int = 16,
) -> list[int]:
    """Return hole sizes except components wholly contained by a binary text mask."""
    rgba = np.asarray(image.convert("RGBA"))
    mask = np.asarray(excluded_mask.convert("L"))
    if mask.shape != rgba.shape[:2]:
        raise ValueError("text mask dimensions must match the inspected image")
    unique = set(int(value) for value in np.unique(mask))
    if not unique.issubset({0, 255}):
        raise ValueError("text mask must be binary (0 or 255)")
    covered = int(np.count_nonzero(mask == 255))
    if covered == 0 or covered > mask.size * 0.6:
        raise ValueError("text mask must cover a non-empty text-only region of at most 60%")
    transparent = rgba[..., 3] < threshold
    holes = transparent & ~edge_connected(transparent)
    sizes: list[int] = []
    for component in _components(holes):
        if all(mask[y, x] == 255 for y, x in component):
            continue
        sizes.append(len(component))
    return sorted(sizes, reverse=True)


def fill_small_transparent_holes(
    image: Image.Image,
    max_pixels: int = 64,
    threshold: int = 16,
    fill: tuple[int, int, int, int] = (255, 255, 255, 255),
) -> Image.Image:
    """Fill accidental micro-holes only; preserve deliberate negative space."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    transparent = rgba[..., 3] < threshold
    holes = transparent & ~edge_connected(transparent)
    for component in _components(holes):
        if len(component) <= max_pixels:
            ys, xs = zip(*component)
            rgba[np.asarray(ys), np.asarray(xs)] = fill
    return Image.fromarray(rgba, "RGBA")


def sanitize_alpha(image: Image.Image, alpha_floor: int = 12) -> Image.Image:
    """Clear RGB for effectively transparent pixels without filling any region."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgba[rgba[..., 3] < alpha_floor] = (0, 0, 0, 0)
    return Image.fromarray(rgba, "RGBA")


def trim_alpha(image: Image.Image, threshold: int = 8) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda p: 255 if p > threshold else 0).getbbox()
    return rgba.crop(bbox) if bbox else rgba


def add_white_outline(image: Image.Image, width: int) -> Image.Image:
    """Add an outline only in transparent space connected to the canvas edge.

    Applying the dilated alpha mask directly would also paint enclosed transparent
    regions, including glyph counters in images with AI-baked text.  Flood-filling
    the original transparent mask from the expanded canvas edge limits the outline
    to the exterior while preserving every enclosed transparent component.
    """
    if width <= 0:
        return image.convert("RGBA")
    image = image.convert("RGBA")
    alpha = ImageOps.expand(image.getchannel("A"), border=width, fill=0)
    dilation = alpha.filter(ImageFilter.MaxFilter(width * 2 + 1))

    # Only fully transparent pixels reachable from the canvas edge are outside.
    # Intersecting with this mask prevents dilation from filling holes/counters and
    # also avoids putting white underneath the source's antialiased alpha pixels.
    alpha_array = np.asarray(alpha)
    exterior = edge_connected(alpha_array == 0)
    outline_alpha = np.where(exterior, np.asarray(dilation), 0).astype(np.uint8)
    outline_mask = Image.fromarray(outline_alpha, "L")

    canvas = Image.new("RGBA", dilation.size, (0, 0, 0, 0))
    canvas.paste(
        Image.new("RGBA", dilation.size, (255, 255, 255, 255)),
        (0, 0),
        outline_mask,
    )
    offset = ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2)
    canvas.alpha_composite(image, offset)
    return canvas


def fit_canvas(image: Image.Image, width: int, height: int, margin: int) -> Image.Image:
    if width % 2 or height % 2:
        raise ValueError("Canvas dimensions must be even")
    fitted = image.convert("RGBA").copy()
    fitted.thumbnail((max(2, width - margin * 2), max(2, height - margin * 2)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def visible_margins(image: Image.Image, threshold: int = 12) -> tuple[int, int, int, int] | None:
    """Measure transparent space around visible alpha as left, top, right, bottom."""
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda value: 255 if value >= threshold else 0).getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    return left, top, rgba.width - right, rgba.height - bottom


def enforce_safe_margin(
    image: Image.Image,
    *,
    required: int = 12,
    target: int = 16,
    threshold: int = 12,
) -> tuple[Image.Image, bool]:
    """Auto-fit all visible content when any edge is below the required margin."""
    if required < 0 or target < required:
        raise ValueError("safe margin target must be at least the required margin")
    rgba = image.convert("RGBA")
    margins = visible_margins(rgba, threshold)
    if margins is None or min(margins) >= required:
        return rgba, False
    bbox = rgba.getchannel("A").point(lambda value: 255 if value >= threshold else 0).getbbox()
    if bbox is None:
        return rgba, False
    inner_width = rgba.width - target * 2
    inner_height = rgba.height - target * 2
    if inner_width < 2 or inner_height < 2:
        raise ValueError("safe margin leaves no drawable content area")
    content = rgba.crop(bbox)
    content.thumbnail((inner_width, inner_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    canvas.alpha_composite(
        content,
        ((rgba.width - content.width) // 2, (rgba.height - content.height) // 2),
    )
    return canvas, True


def save_png(image: Image.Image, path: Path, max_bytes: int = 1_000_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG", optimize=True, compress_level=9, dpi=(72, 72))
    data = buffer.getvalue()
    if len(data) > max_bytes:
        raise ValueError(f"{path.name} is {len(data)} bytes; reduce source complexity or dimensions")
    path.write_bytes(data)


def hidden_rgb_pixels(image: Image.Image, alpha_limit: int = 12) -> int:
    rgba = np.asarray(image.convert("RGBA"))
    return int(np.count_nonzero((rgba[..., 3] < alpha_limit) & np.any(rgba[..., :3] != 0, axis=2)))
