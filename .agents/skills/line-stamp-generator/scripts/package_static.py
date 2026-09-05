#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from image_utils import fit_canvas, sanitize_alpha, save_png, trim_alpha
from project_context import enforce_facade_project
from session_contract import (
    load_static_session,
    project_stamp_name,
    session_count,
    submission_stamp_name,
)
from transaction_utils import ArtifactRollbackError, exclusive_lock, install_files_transaction


ALLOWED_COUNTS = {8, 16, 24, 32, 40}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def checked_zip_name(zip_name: str, managed_names: set[str]) -> str:
    if (
        not zip_name
        or "/" in zip_name
        or "\\" in zip_name
        or Path(zip_name).name != zip_name
        or Path(zip_name).suffix.lower() != ".zip"
        or any(character in '<>:"|?*' or ord(character) < 32 for character in zip_name)
        or zip_name.split(".", 1)[0].rstrip(" .").upper() in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("zip-name must be a plain .zip filename without directory components")
    if zip_name in managed_names:
        raise ValueError(f"zip-name collides with a packaged image: {zip_name}")
    return zip_name


def load_rgba(path: Path) -> Image.Image:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Missing image: {path}")
    with Image.open(path) as opened:
        opened.load()
        return opened.convert("RGBA")


def checked_package_directories(
    source_dir: Path, outdir: Path, character_dir: Path | None
) -> tuple[Path, Path, Path | None]:
    """Keep package inputs and outputs inside one project workspace."""
    raw_paths = (
        ("stamps", source_dir),
        ("submit", outdir),
        ("character-layers", character_dir),
    )
    for label, path in raw_paths:
        if path is not None and path.is_symlink():
            raise ValueError(f"{label} directory must not be a symlink")
    if source_dir.parent.is_symlink():
        raise ValueError("project directory must not be a symlink")
    source_dir = source_dir.resolve()
    outdir = outdir.resolve()
    character_dir = character_dir.resolve() if character_dir else None
    project_dir = source_dir.parent
    enforce_facade_project(project_dir, "package")
    projects_dir = project_dir.parent
    if projects_dir.name != "projects" or project_dir.is_symlink():
        raise ValueError("package paths must belong to projects/<slug>/")
    active_path = projects_dir / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file during packaging")
    try:
        active = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read projects/ACTIVE as UTF-8: {exc}") from exc
    if active != project_dir.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select packaging project {project_dir.name!r}"
        )
    if source_dir != project_dir / "stamps":
        raise ValueError("--stamps must be the project's stamps/ directory")
    if outdir != project_dir / "submit":
        raise ValueError("--outdir must be the same project's submit/ directory")
    if character_dir is not None and character_dir != project_dir / "character-layers":
        raise ValueError("--character-dir must be the same project's character-layers/ directory")
    return source_dir, outdir, character_dir


def package_static(
    source_dir: Path,
    outdir: Path,
    count: int,
    main_index: int = 1,
    tab_index: int = 1,
    character_dir: Path | None = None,
    zip_name: str = "line-stamp-submit.zip",
) -> Path:
    if count not in ALLOWED_COUNTS:
        raise ValueError(f"Static count must be one of {sorted(ALLOWED_COUNTS)}")
    if main_index not in range(1, count + 1):
        raise ValueError(f"main-index must be between 1 and {count}")
    if tab_index not in range(1, count + 1):
        raise ValueError(f"tab-index must be between 1 and {count}")

    source_dir, outdir, checked_character_dir = checked_package_directories(
        Path(source_dir), Path(outdir), Path(character_dir) if character_dir else None
    )
    session = load_static_session(source_dir.parent, {"P6"})
    if count != session_count(session):
        raise ValueError(f"--count {count} differs from SESSION count {session['count']}")
    stamp_pairs = [
        (source_dir / project_stamp_name(index), submission_stamp_name(index))
        for index in range(1, count + 1)
    ]
    missing = [
        source.name
        for source, _ in stamp_pairs
        if source.is_symlink() or not source.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"Missing stamps: {missing}")

    submitted_stamp_names = [submitted_name for _, submitted_name in stamp_pairs]
    managed_image_names = {"main.png", "tab.png", *submitted_stamp_names}
    zip_name = checked_zip_name(zip_name, managed_image_names)
    hero_dir = checked_character_dir if checked_character_dir else source_dir
    main_source = trim_alpha(load_rgba(hero_dir / project_stamp_name(main_index)))
    tab_source = trim_alpha(load_rgba(hero_dir / project_stamp_name(tab_index)))

    outdir.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    preserve_staging = False
    try:
        with exclusive_lock(outdir / ".line-stamp-package.lock", "package-static transaction"):
            staging = Path(tempfile.mkdtemp(prefix=".line-stamp-package-", dir=outdir))
            for source, submitted_name in stamp_pairs:
                shutil.copy2(source, staging / submitted_name)

            save_png(sanitize_alpha(fit_canvas(main_source, 240, 240, 10)), staging / "main.png")
            upper = trim_alpha(
                tab_source.crop((0, 0, tab_source.width, max(2, round(tab_source.height * 0.58))))
            )
            save_png(sanitize_alpha(fit_canvas(upper, 96, 74, 4)), staging / "tab.png")

            staged_zip = staging / zip_name
            member_names = ["main.png", "tab.png", *submitted_stamp_names]
            with zipfile.ZipFile(staged_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in member_names:
                    archive.write(staging / name, name)

            install_names = [*submitted_stamp_names, "main.png", "tab.png", zip_name]
            # Staging and backups live under outdir, so every replace stays on one
            # filesystem. The ZIP is installed last; failures restore the complete
            # prior managed set, while unrelated files and directories are untouched.
            try:
                install_files_transaction(
                    staging,
                    [(staging / name, outdir / name) for name in install_names],
                )
            except ArtifactRollbackError:
                preserve_staging = True
                raise
    finally:
        if staging is not None and staging.exists() and not preserve_staging:
            shutil.rmtree(staging)

    zip_path = outdir / zip_name
    print(f"wrote {zip_path} {zip_path.stat().st_size}B members={count + 2}")
    legacy_names = [
        project_stamp_name(index)
        for index in range(1, max(ALLOWED_COUNTS) + 1)
        if (outdir / project_stamp_name(index)).is_file()
        or (outdir / project_stamp_name(index)).is_symlink()
    ]
    if legacy_names:
        print(
            "WARN preserved legacy submit files excluded from ZIP: "
            + ", ".join(legacy_names)
        )
    return zip_path


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

    package_static(
        source_dir=Path(args.stamps),
        outdir=Path(args.outdir),
        count=args.count,
        main_index=args.main_index,
        tab_index=args.tab_index,
        character_dir=Path(args.character_dir) if args.character_dir else None,
        zip_name=args.zip_name,
    )


if __name__ == "__main__":
    main()
