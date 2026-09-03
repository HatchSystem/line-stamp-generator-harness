#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from PIL import Image

from image_utils import fit_canvas, sanitize_alpha, save_png, trim_alpha


ALLOWED_COUNTS = {8, 16, 24, 32, 40}


def main() -> None:
    parser = argparse.ArgumentParser(description="Package already composed static LINE stamps")
    parser.add_argument("--stamps", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--main-index", type=int, default=1)
    parser.add_argument("--tab-index", type=int, default=1)
    parser.add_argument("--character-dir", help="Prefer character-only layers for main and tab")
    parser.add_argument("--zip-name", default="line-stamp-submit.zip")
    args = parser.parse_args()

    if args.count not in ALLOWED_COUNTS:
        raise ValueError(f"Static count must be one of {sorted(ALLOWED_COUNTS)}")
    source_dir = Path(args.stamps)
    expected = [source_dir / f"stamp{index:02d}.png" for index in range(1, args.count + 1)]
    missing = [path.name for path in expected if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing stamps: {missing}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for path in outdir.glob("stamp*.png"):
        path.unlink()
    for name in ("main.png", "tab.png", args.zip_name):
        path = outdir / name
        if path.exists():
            path.unlink()

    for source in expected:
        shutil.copy2(source, outdir / source.name)

    hero_dir = Path(args.character_dir) if args.character_dir else source_dir
    main_source = trim_alpha(Image.open(hero_dir / f"stamp{args.main_index:02d}.png").convert("RGBA"))
    tab_source = trim_alpha(Image.open(hero_dir / f"stamp{args.tab_index:02d}.png").convert("RGBA"))
    save_png(sanitize_alpha(fit_canvas(main_source, 240, 240, 10)), outdir / "main.png")

    upper = trim_alpha(tab_source.crop((0, 0, tab_source.width, max(2, round(tab_source.height * 0.58)))))
    save_png(sanitize_alpha(fit_canvas(upper, 96, 74, 4)), outdir / "tab.png")

    zip_path = outdir / args.zip_name
    members = [outdir / "main.png", outdir / "tab.png", *[outdir / path.name for path in expected]]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in members:
            archive.write(path, path.name)
    print(f"wrote {zip_path} {zip_path.stat().st_size}B members={len(members)}")


if __name__ == "__main__":
    main()
