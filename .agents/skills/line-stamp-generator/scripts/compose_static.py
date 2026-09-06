#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from image_utils import (
    enforce_safe_margin,
    fill_small_transparent_holes,
    sanitize_alpha,
    save_png,
    trim_alpha,
)
from metadata_utils import loads_no_duplicates
from project_context import enforce_facade_project
from session_contract import load_static_session, session_count
from transaction_utils import ArtifactRollbackError, exclusive_lock, install_files_transaction


def checked_text_mode(style: dict) -> str:
    """Reject retired font composition settings instead of silently ignoring them."""
    mode = style.get("text_mode")
    if mode == "font":
        raise ValueError("font composition is no longer supported; create a new ai project")
    if mode not in ("ai", "none"):
        raise ValueError("style.text_mode must be explicitly ai or none")
    retired = {
        "font", "text_zone_height", "text_fill", "text_outline", "outline_width",
        "line_spacing", "max_font_size", "min_font_size",
    }.intersection(style)
    if retired:
        raise ValueError(
            f"font composition settings are no longer supported: {sorted(retired)}; "
            "describe lettering in the approved generation prompt instead"
        )
    return mode


def resolve_project_file(base: Path, value: str, label: str) -> Path:
    """Resolve a required manifest input without crossing the project boundary."""
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{label} must be a project-relative path")
    candidate = base / path
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base.resolve()) or not resolved.is_file():
        raise ValueError(f"{label} must name an existing file inside the project")
    return resolved


def checked_output_directories(
    base: Path,
    outdir_value: str,
    character_value: str,
) -> tuple[Path, Path]:
    """Bind each artifact class to its canonical, non-overlapping project directory."""
    base = base.resolve()
    raw_outdir = Path(outdir_value)
    raw_character_dir = Path(character_value)
    for label, path in (
        ("--outdir", raw_outdir),
        ("--character-layer-dir", raw_character_dir),
    ):
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
    outdir = raw_outdir.resolve()
    character_dir = raw_character_dir.resolve()
    expected = {
        "--outdir": base / "stamps",
        "--character-layer-dir": base / "character-layers",
    }
    actual = {
        "--outdir": outdir,
        "--character-layer-dir": character_dir,
    }
    for label, expected_path in expected.items():
        if actual[label] != expected_path:
            raise ValueError(f"{label} must be {expected_path} for this project")
        if not actual[label].is_relative_to(base):
            raise ValueError(f"{label} escapes the project")
    if len(set(actual.values())) != len(actual):
        raise ValueError("compose output directories must resolve to distinct locations")
    return outdir, character_dir


def checked_items(value: object) -> list[dict]:
    """Reject ambiguous manifest entries before any output can be overwritten."""
    if not isinstance(value, list) or not value:
        raise ValueError("manifest.items must be a nonempty list")
    result: list[dict] = []
    seen: set[int] = set()
    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest.items[{position}] must be an object")
        item_id = item.get("id")
        if type(item_id) is not int or item_id not in range(1, 41):
            raise ValueError(f"manifest.items[{position}].id must be an integer from 1 through 40")
        if item_id in seen:
            raise ValueError(f"manifest.items contains duplicate id {item_id}")
        seen.add(item_id)
        character = item.get("character")
        if not isinstance(character, str) or not character.strip():
            raise ValueError(f"manifest.items[{position}].character must be a nonempty path")
        text = item.get("text", [])
        if not isinstance(text, str) and not (
            isinstance(text, list) and all(isinstance(line, str) for line in text)
        ):
            raise ValueError(f"manifest.items[{position}].text must be a string or list of strings")
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Place AI-lettered or text-free images on transparent canvases; font composition and --text-layer-dir are no longer supported")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--character-layer-dir", required=True)
    args = parser.parse_args()

    raw_manifest_path = Path(args.manifest)
    if raw_manifest_path.is_symlink() or not raw_manifest_path.is_file():
        raise ValueError("--manifest must be a regular non-symlink file")
    if raw_manifest_path.name != "manifest.json" or raw_manifest_path.parent.is_symlink():
        raise ValueError("--manifest must be projects/<slug>/manifest.json")
    raw_project = raw_manifest_path.parent
    enforce_facade_project(raw_project, "compose")
    projects_dir = raw_project.parent
    if projects_dir.name != "projects":
        raise ValueError("--manifest must belong to projects/<slug>/")
    active_path = projects_dir / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file during composition")
    try:
        active = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read projects/ACTIVE as UTF-8: {exc}") from exc
    if active != raw_project.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select compose project {raw_project.name!r}"
        )
    manifest_path = raw_manifest_path.resolve()
    manifest = loads_no_duplicates(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    base = manifest_path.parent
    session = load_static_session(base, {"P4", "P5"})
    style = manifest.get("style")
    if not isinstance(style, dict):
        raise ValueError("manifest.style must be an object")
    if style.get("shadow"):
        raise ValueError("Text shadows are disabled; use a concentric outline only")
    text_mode = checked_text_mode(style)
    if text_mode != session["text_mode"]:
        raise ValueError(
            f"manifest style.text_mode={text_mode!r} differs from SESSION "
            f"text_mode={session['text_mode']!r}"
        )

    canvas = style.get("canvas", [370, 320])
    if (
        not isinstance(canvas, list)
        or len(canvas) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in canvas)
    ):
        raise ValueError("style.canvas must contain two positive integers")
    canvas_width, canvas_height = canvas
    if canvas_width % 2 or canvas_height % 2:
        raise ValueError("Canvas dimensions must be even")
    margin = int(style.get("margin", 10))
    safe_margin = int(style.get("safe_margin", 16))
    if margin < 0:
        raise ValueError("style.margin must be nonnegative")
    if safe_margin not in range(12, 17):
        raise ValueError("style.safe_margin must be from 12 through 16 pixels")
    if margin * 2 >= canvas_width or margin >= canvas_height:
        raise ValueError("style margins leave no drawable character area")

    outdir, character_layer_dir = checked_output_directories(
        base,
        args.outdir,
        args.character_layer_dir,
    )
    alpha_floor = int(style.get("alpha_floor", 12))
    if alpha_floor not in range(0, 256):
        raise ValueError("style.alpha_floor must be from 0 through 255")

    items = checked_items(manifest.get("items"))
    item_ids = {int(item["id"]) for item in items}
    expected_ids = set(range(1, session_count(session) + 1))
    if session["gate"] == "P4" and item_ids != {1}:
        raise ValueError("P4 composition must contain only manifest item id 1")
    if session["gate"] == "P5" and item_ids != expected_ids:
        raise ValueError(
            "P5 composition requires manifest ids exactly 1..SESSION count; "
            f"missing={sorted(expected_ids - item_ids)} extra={sorted(item_ids - expected_ids)}"
        )
    staging: Path | None = None
    preserve_staging = False
    messages: list[str] = []
    try:
        with exclusive_lock(base / ".line-stamp-compose.lock", "compose-static transaction"):
            staging = Path(tempfile.mkdtemp(prefix=".line-stamp-compose-", dir=base))
            installs: list[tuple[Path, Path]] = []
            for item in items:
                index = int(item["id"])
                lines = item.get("text", [])
                if isinstance(lines, str):
                    lines = lines.split("\n") if lines else []
                if text_mode == "ai" and not any(line.strip() for line in lines):
                    raise ValueError(f"text_mode=ai requires approved text for item {index}")
                if text_mode == "none" and any(line for line in lines):
                    raise ValueError(f"text_mode=none requires empty text for item {index}")
                character_path = resolve_project_file(base, item["character"], f"item {index} character")
                canonical_character_dir = base / "characters"
                canonical_character = canonical_character_dir / f"stamp{index:02d}.png"
                if canonical_character_dir.is_symlink() or character_path != canonical_character.resolve():
                    raise ValueError(
                        f"item {index} character must be characters/stamp{index:02d}.png "
                        "produced by preprocess-character"
                    )
                with Image.open(character_path) as opened:
                    character = trim_alpha(opened.convert("RGBA"))
                character.thumbnail(
                    (canvas_width - margin * 2, canvas_height - margin),
                    Image.Resampling.LANCZOS,
                )
                if text_mode != "ai":  # ai mode: baked text counters must never be filled
                    character = fill_small_transparent_holes(
                        character, max_pixels=int(style.get("max_hole_pixels_after_resize", 64))
                    )
                character = sanitize_alpha(character, alpha_floor)

                character_layer = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
                character_x = (canvas_width - character.width) // 2
                character_y = canvas_height - margin - character.height
                character_layer.alpha_composite(character, (character_x, character_y))

                final = sanitize_alpha(character_layer, alpha_floor)
                final, margin_adjusted = enforce_safe_margin(
                    final,
                    required=12,
                    target=safe_margin,
                    threshold=alpha_floor,
                )
                final = sanitize_alpha(final, alpha_floor)
                name = f"stamp{index:02d}.png"
                staged_final = staging / "stamps" / name
                staged_character = staging / "character-layers" / name
                save_png(final, staged_final)
                save_png(sanitize_alpha(character_layer, alpha_floor), staged_character)
                installs.extend(
                    [(staged_final, outdir / name), (staged_character, character_layer_dir / name)]
                )
                messages.append(
                    f"wrote {name} mode={text_mode} text={'/'.join(lines)} "
                    f"safe-margin={'adjusted' if margin_adjusted else 'ok'}"
                )

            for directory in (outdir, character_layer_dir):
                directory.mkdir(parents=True, exist_ok=True)
            try:
                install_files_transaction(staging, installs)
            except ArtifactRollbackError:
                preserve_staging = True
                raise
    finally:
        if staging is not None and staging.exists() and not preserve_staging:
            shutil.rmtree(staging)

    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
