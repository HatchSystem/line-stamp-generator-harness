"""Create automatic AI-text evidence and versioned text-region masks."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from metadata_utils import loads_no_duplicates
from project_context import enforce_facade_project
from session_contract import load_static_session, read_regular_bytes
from transaction_utils import exclusive_lock

WHITESPACE = re.compile(r"[\s\u3000]+")
LOOSE_STRIP = re.compile(r"[!！?？。、,，.．・:：;；()（）\[\]「」『』\"'…♪☆★♡♥〜~ー―—-]+")
VISION_PROVIDER_BLOCKLIST = {"agent", "main-agent", "user", "manual", "visual-only"}


def normalize(text: str, loose: bool) -> str:
    text = unicodedata.normalize("NFKC" if loose else "NFC", text)
    text = WHITESPACE.sub("", text)
    return LOOSE_STRIP.sub("", text).lower() if loose else text


def checked_project_paths(
    manifest_value: str, stamp_value: str, review_value: str
) -> tuple[Path, Path, Path]:
    raw_manifest = Path(manifest_value)
    raw_stamps = Path(stamp_value)
    raw_review = Path(review_value)
    if raw_manifest.is_symlink() or not raw_manifest.is_file():
        raise ValueError("--manifest must be a regular non-symlink project manifest.json")
    if raw_manifest.name != "manifest.json" or raw_manifest.parent.is_symlink():
        raise ValueError("--manifest must be projects/<slug>/manifest.json")
    for label, path in (("--dir", raw_stamps), ("--review-dir", raw_review)):
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
    project_dir = raw_manifest.parent.resolve()
    enforce_facade_project(project_dir, "text verification")
    manifest = raw_manifest.resolve()
    stamps = raw_stamps.resolve()
    review = raw_review.resolve()
    if stamps != project_dir / "stamps":
        raise ValueError("--dir must be the same project's stamps/ directory")
    if review != project_dir / "review":
        raise ValueError("--review-dir must be the same project's review/ directory")
    if project_dir.parent.name != "projects":
        raise ValueError("verify-text paths must belong to projects/<slug>/")
    active_path = project_dir.parent / "ACTIVE"
    if active_path.is_symlink() or not active_path.is_file():
        raise ValueError("projects/ACTIVE must be a regular non-symlink file")
    active = active_path.read_text(encoding="utf-8").strip()
    if active != project_dir.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select project {project_dir.name!r}"
        )
    return manifest, stamps, review


def ocr_available(lang: str) -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "pytesseract is not installed"
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
    except Exception as exc:
        return False, f"Tesseract is unavailable: {exc}"
    missing = [part for part in lang.split("+") if part not in languages]
    if missing:
        return False, f"Tesseract language data is missing: {missing}"
    return True, ""


def prepare(image: Image.Image, scale: int) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat = ImageOps.autocontrast(Image.alpha_composite(white, rgba).convert("L"))
    if scale > 1:
        flat = flat.resize(
            (flat.width * scale, flat.height * scale), Image.Resampling.LANCZOS
        )
    return flat


def run_ocr(image: Image.Image, lang: str, scale: int) -> str:
    import pytesseract

    best = ""
    for psm in (6, 7, 11):
        candidate = pytesseract.image_to_string(
            prepare(image, scale), lang=lang, config=f"--psm {psm}"
        ).strip()
        if len(candidate) > len(best):
            best = candidate
    return best


def next_version(review_dir: Path) -> int:
    versions = [
        int(match.group(1))
        for path in review_dir.glob("text-check-v*.*")
        if (match := re.fullmatch(r"text-check-v(\d+)\.(?:md|json)", path.name))
    ]
    return max(versions, default=0) + 1


def verification_session(project_dir: Path) -> tuple[dict[str, str], list[str]]:
    try:
        values = load_static_session(project_dir, {"P4", "P5"})
    except ValueError as exc:
        return {}, [str(exc)]
    errors = []
    if values.get("text") != "yes" or values.get("text_mode") != "ai":
        errors.append("verify-text requires SESSION text=yes and text_mode=ai")
    return values, errors


def verification_scope(
    session: dict[str, str], manifest_ids: set[int], requested_ids: set[int] | None
) -> set[int]:
    count = int(session["count"])
    expected_ids = set(range(1, count + 1))
    extra = sorted(manifest_ids - expected_ids)
    if extra:
        raise ValueError(f"manifest ids exceed SESSION count: {extra}")
    if session["gate"] == "P4":
        if requested_ids != {1} or 1 not in manifest_ids:
            raise ValueError("P4 requires --only 1 and a manifest item for stamp01")
        return {1}
    if manifest_ids != expected_ids:
        raise ValueError(
            "P5 requires manifest ids exactly 1..SESSION count; "
            f"missing={sorted(expected_ids - manifest_ids)} extra={extra}"
        )
    if requested_ids is not None:
        raise ValueError("P5 final evidence must recheck every id; omit --only")
    return expected_ids


def parse_requested_ids(value: str | None, manifest_ids: set[int]) -> set[int] | None:
    if value is None:
        return None
    tokens = [part.strip() for part in value.split(",")]
    if not tokens or any(not token for token in tokens):
        raise ValueError("--only requires comma-separated stamp ids")
    try:
        ids = [int(token) for token in tokens]
    except ValueError as exc:
        raise ValueError("--only stamp ids must be integers") from exc
    if any(item_id not in range(1, 41) for item_id in ids):
        raise ValueError("--only stamp ids must be from 1 through 40")
    if len(ids) != len(set(ids)):
        raise ValueError("--only must not contain duplicate ids")
    absent = sorted(set(ids) - manifest_ids)
    if absent:
        raise ValueError(f"--only ids are missing from manifest: {absent}")
    return set(ids)


def expected_text(item: dict, position: int) -> str:
    value = item.get("text")
    if isinstance(value, str):
        result = value
    elif isinstance(value, list) and value and all(isinstance(line, str) for line in value):
        result = "".join(value)
    else:
        raise ValueError(f"manifest.items[{position}].text must be a string or string list")
    if not normalize(result, False):
        raise ValueError(f"manifest.items[{position}].text must not be empty")
    return result


def text_region(item: dict, size: tuple[int, int], position: int) -> tuple[int, int, int, int]:
    """Validate the tight text-only rectangle used to protect glyph counters."""
    value = item.get("text_region")
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(number) is not int for number in value)
    ):
        raise ValueError(
            f"manifest.items[{position}].text_region must be [left, top, right, bottom] integers"
        )
    left, top, right, bottom = value
    width, height = size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(
            f"manifest.items[{position}].text_region is outside the {width}x{height} stamp"
        )
    if (right - left) * (bottom - top) > width * height * 0.6:
        raise ValueError(
            f"manifest.items[{position}].text_region covers over 60% of the stamp; "
            "use a tight text-only region"
        )
    return left, top, right, bottom


def mask_payload(size: tuple[int, int], region: tuple[int, int, int, int]) -> bytes:
    mask = Image.new("L", size, 0)
    left, top, right, bottom = region
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    output = io.BytesIO()
    mask.save(output, format="PNG", optimize=False)
    return output.getvalue()


def load_vision_evidence(
    value: str,
    project_dir: Path,
    manifest_sha256: str,
    selected_ids: set[int],
) -> tuple[str, str, dict[int, dict], str, str]:
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("--vision-evidence must be a regular non-symlink JSON file")
    resolved = path.resolve()
    if not resolved.is_relative_to(project_dir.resolve()):
        raise ValueError("--vision-evidence must stay inside the active project")
    allowed = ((project_dir / "review").resolve(), (project_dir / "meta").resolve())
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise ValueError("--vision-evidence must stay under project review/ or meta/")
    source_payload = read_regular_bytes(resolved)
    payload = loads_no_duplicates(source_payload.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("vision evidence must be a schema_version 1 object")
    provider = payload.get("provider")
    model = payload.get("model")
    generated_at = payload.get("generated_at")
    if (
        not isinstance(provider, str)
        or not provider.strip()
        or provider.strip().lower() in VISION_PROVIDER_BLOCKLIST
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(generated_at, str)
        or not generated_at.strip()
    ):
        raise ValueError("vision evidence requires an independent provider, model, and generated_at")
    try:
        generated_datetime = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ValueError("vision evidence generated_at must be an ISO-8601 datetime") from exc
    if generated_datetime.tzinfo is None:
        raise ValueError("vision evidence generated_at must include a UTC offset")
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError("vision evidence does not match current manifest.json")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("vision evidence items must be an array")
    by_id: dict[int, dict] = {}
    for row in items:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError("vision evidence contains an invalid item")
        row_id = row["id"]
        if row_id in by_id:
            raise ValueError(f"vision evidence duplicates id {row_id}")
        by_id[row_id] = row
    if set(by_id) != selected_ids:
        raise ValueError("vision evidence ids do not match the requested scope")
    source_file = resolved.relative_to(project_dir.resolve()).as_posix()
    return (
        provider.strip(),
        model.strip(),
        by_id,
        source_file,
        hashlib.sha256(source_payload).hexdigest(),
    )


def classify(expected: str, recognized: str, minimum: float) -> tuple[str, float]:
    strict = normalize(expected, False) == normalize(recognized, False)
    loose_expected = normalize(expected, True)
    loose_recognized = normalize(recognized, True)
    similarity = difflib.SequenceMatcher(None, loose_expected, loose_recognized).ratio()
    if strict:
        return "match", round(similarity, 3)
    if loose_expected == loose_recognized or similarity >= minimum:
        return "near", round(similarity, 3)
    return "mismatch", round(similarity, 3)


def write_new_files(entries: list[tuple[Path, bytes]]) -> None:
    created: list[tuple[Path, os.stat_result]] = []
    try:
        for path, payload in entries:
            with path.open("xb") as destination:
                identity = os.fstat(destination.fileno())
                created.append((path, identity))
                written = destination.write(payload)
                if written != len(payload):
                    raise OSError(f"short write for {path}: {written}/{len(payload)} bytes")
    except BaseException:
        for path, identity in reversed(created):
            try:
                current = path.stat(follow_symlinks=False)
            except (FileNotFoundError, OSError):
                current = None
            if current is not None and not path.is_symlink() and os.path.samestat(identity, current):
                path.unlink()
        raise


def build_rows(
    manifest_items: list,
    selected_ids: set[int],
    stamp_dir: Path,
    available: bool,
    vision_rows: dict[int, dict],
    automatic_provider: str,
    lang: str,
    scale: int,
    minimum: float,
) -> tuple[list[dict], dict[int, bytes]]:
    rows: list[dict] = []
    masks: dict[int, bytes] = {}
    for position, item in enumerate(manifest_items, start=1):
        index = int(item["id"])
        if index not in selected_ids:
            continue
        path = stamp_dir / f"stamp{index:02d}.png"
        row: dict = {
            "id": index,
            "file": path.name,
            "sha256": None,
            "expected": "",
            "automatic_text": "",
            "automatic_provider": automatic_provider or None,
            "status": "",
            "similarity": None,
            "text_region": item.get("text_region"),
            "mask_file": None,
            "mask_sha256": None,
        }
        try:
            expected = expected_text(item, position)
            row["expected"] = expected
            stamp_payload = read_regular_bytes(path)
            row["sha256"] = hashlib.sha256(stamp_payload).hexdigest()
            with Image.open(io.BytesIO(stamp_payload)) as opened:
                opened.load()
                image = opened.convert("RGBA")
            region = text_region(item, image.size, position)
            row["text_region"] = list(region)
            masks[index] = mask_payload(image.size, region)
            if available:
                recognized = run_ocr(image, lang, scale)
            elif vision_rows:
                vision_row = vision_rows[index]
                if (
                    vision_row.get("file") != path.name
                    or vision_row.get("sha256") != row["sha256"]
                    or vision_row.get("expected") != expected
                    or not isinstance(vision_row.get("recognized"), str)
                ):
                    raise ValueError(f"vision evidence does not match current {path.name}")
                recognized = vision_row["recognized"]
            else:
                recognized = ""
            row["automatic_text"] = recognized.replace("\n", "/")
            if automatic_provider:
                row["status"], row["similarity"] = classify(expected, recognized, minimum)
            else:
                row["status"] = "automatic-unavailable"
        except (OSError, ValueError, RuntimeError) as exc:
            row["status"] = "unreadable"
            row["error"] = str(exc)
        rows.append(row)
    return rows, masks


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Create automatic evidence and text masks for AI-drawn stamp text"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dir", required=True, help="same project's stamps/ directory")
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--lang", default="jpn+eng")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--only", help="P4 only: comma-separated stamp ids")
    parser.add_argument(
        "--vision-evidence",
        help="independent vision JSON fallback used only when Tesseract is unavailable",
    )
    parser.add_argument("--min-similarity", type=float, default=0.85)
    args = parser.parse_args()
    if not 1 <= args.scale <= 8:
        print("ERROR verify-text: --scale must be from 1 through 8")
        return 1
    if not 0.0 <= args.min_similarity <= 1.0:
        print("ERROR verify-text: --min-similarity must be from 0 through 1")
        return 1

    try:
        manifest_path, stamp_dir, review_dir = checked_project_paths(
            args.manifest, args.dir, args.review_dir
        )
        session, session_errors = verification_session(manifest_path.parent)
        if session_errors:
            raise ValueError("; ".join(session_errors))
        manifest_payload = read_regular_bytes(manifest_path)
        manifest = loads_no_duplicates(manifest_payload.decode("utf-8"))
        manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
        if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
            raise ValueError("manifest root must contain an items array")
        items_by_id: dict[int, dict] = {}
        for position, item in enumerate(manifest["items"], start=1):
            if not isinstance(item, dict) or type(item.get("id")) is not int:
                raise ValueError(f"manifest.items[{position}] requires an integer id")
            item_id = item["id"]
            if item_id not in range(1, 41) or item_id in items_by_id:
                raise ValueError(f"manifest.items[{position}].id is invalid or duplicated")
            items_by_id[item_id] = item
        requested = parse_requested_ids(args.only, set(items_by_id))
        selected_ids = verification_scope(session, set(items_by_id), requested)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR verify-text: {exc}")
        return 1

    available, reason = ocr_available(args.lang)
    automatic_provider = "tesseract" if available else ""
    automatic_model = args.lang if available else ""
    automatic_method = "ocr" if available else ""
    vision_rows: dict[int, dict] = {}
    vision_source_file: str | None = None
    vision_source_sha256: str | None = None
    if not available and args.vision_evidence:
        try:
            (
                automatic_provider,
                automatic_model,
                vision_rows,
                vision_source_file,
                vision_source_sha256,
            ) = load_vision_evidence(
                args.vision_evidence, manifest_path.parent, manifest_sha256, selected_ids
            )
            automatic_method = "vision"
            reason = "Tesseract unavailable; independent vision evidence used"
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"ERROR verify-text: invalid vision fallback: {exc}")
            return 1

    rows, masks = build_rows(
        manifest["items"], selected_ids, stamp_dir, available, vision_rows,
        automatic_provider, args.lang, args.scale, args.min_similarity
    )
    try:
        if review_dir.exists() and not review_dir.is_dir():
            raise ValueError("review path must be a directory")
        review_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        print(f"ERROR verify-text: cannot prepare review directory: {exc}")
        return 1
    mask_root = manifest_path.parent / "text-masks"
    if mask_root.is_symlink() or (mask_root.exists() and not mask_root.is_dir()):
        print("ERROR verify-text: text-masks must be a regular non-symlink directory")
        return 1
    try:
        mask_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR verify-text: cannot prepare text-masks directory: {exc}")
        return 1
    try:
        with exclusive_lock(review_dir / ".line-stamp-verify.lock", "verify-text transaction"):
            version = next_version(review_dir)
            mask_dir = mask_root / f"v{version:02d}"
            if mask_dir.exists() or mask_dir.is_symlink():
                raise ValueError(f"versioned mask directory already exists: {mask_dir.name}")
            mask_dir.mkdir()
            try:
                entries: list[tuple[Path, bytes]] = []
                for row in rows:
                    if row["id"] not in masks:
                        continue
                    mask_name = f"stamp{row['id']:02d}.png"
                    payload = masks[row["id"]]
                    row["mask_file"] = f"text-masks/v{version:02d}/{mask_name}"
                    row["mask_sha256"] = hashlib.sha256(payload).hexdigest()
                    entries.append((mask_dir / mask_name, payload))
                scope = "sample" if session["gate"] == "P4" else "all"
                report = {
                    "schema_version": 2,
                    "version": version,
                    "project": manifest_path.parent.name,
                    "gate": session["gate"],
                    "scope": scope,
                    "session_count": int(session["count"]),
                    "manifest_sha256": manifest_sha256,
                    "automatic_available": bool(automatic_provider),
                    "automatic_method": automatic_method or None,
                    "automatic_provider": automatic_provider or None,
                    "automatic_model": automatic_model or None,
                    "vision_evidence_file": vision_source_file,
                    "vision_evidence_sha256": vision_source_sha256,
                    "reason": reason,
                    "rows": rows,
                }
                lines = [
                    f"# text-check v{version:02d}", "",
                    f"- project: `{manifest_path.parent.name}`",
                    f"- gate: `{session['gate']}`", f"- scope: `{scope}`",
                    f"- automatic: `{automatic_provider or 'unavailable'}`",
                    f"- model/language: `{automatic_model or 'n/a'}`",
                    "- user approval: required before setting SESSION text_check=ok", "",
                    "| id | expected | automatic text | similarity | status | mask |",
                    "|---|---|---|---|---|---|",
                ]
                for row in rows:
                    similarity = "" if row["similarity"] is None else f"{row['similarity']:.2f}"
                    expected = str(row["expected"]).replace("|", "\\|")
                    recognized = str(row["automatic_text"]).replace("|", "\\|")
                    mask_name = Path(row["mask_file"]).name if row["mask_file"] else ""
                    lines.append(
                        f"| {row['id']:02d} | {expected} | {recognized} | {similarity} | "
                        f"{row['status']} | {mask_name} |"
                    )
                lines.extend([
                    "", "Automatic checking never replaces agent visual reading or user approval.",
                    "`near` and `mismatch` require explicit visual reconciliation or regeneration.",
                    "`automatic-unavailable` cannot satisfy P6; use Tesseract or independent vision evidence.",
                    "Text masks exclude only declared text regions from micro-hole checks.", "",
                ])
                md_path = review_dir / f"text-check-v{version:02d}.md"
                json_path = review_dir / f"text-check-v{version:02d}.json"
                entries.extend([
                    (md_path, "\n".join(lines).encode("utf-8")),
                    (json_path, (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")),
                ])
                write_new_files(entries)
            except BaseException:
                if mask_dir.is_dir() and not mask_dir.is_symlink():
                    for child in mask_dir.iterdir():
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                    mask_dir.rmdir()
                raise
    except (OSError, ValueError) as exc:
        print(f"ERROR verify-text: could not write evidence: {exc}")
        return 1

    statuses = ("match", "near", "mismatch", "automatic-unavailable", "unreadable")
    counts = {status: sum(row["status"] == status for row in rows) for status in statuses}
    print(
        f"text-check v{version:02d}: checked={len(rows)} provider={automatic_provider or 'none'} "
        + " ".join(f"{key}={value}" for key, value in counts.items())
    )
    print(f"report: {md_path}")
    print(f"masks: {mask_dir}")
    if counts["unreadable"]:
        return 1
    if not automatic_provider:
        print("Automatic text checking is unavailable; P6 remains blocked.")
        return 2
    return 1 if counts["near"] or counts["mismatch"] else 0
