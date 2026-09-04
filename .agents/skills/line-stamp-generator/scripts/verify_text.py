#!/usr/bin/env python3
"""Verify that AI-drawn text in stamp images matches the approved lines in the manifest.

Used only when SESSION text_mode=ai. Runs OCR on each image, normalizes both sides, and writes
review/text-check-vNN.md (+ .json). OCR is a first pass only: the agent must still read every image
and the user must approve before SESSION text_check becomes ok.

Exit codes: 0 all strictly matched / 1 review or input correction required /
2 OCR unavailable (visual check required)
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps

from metadata_utils import DuplicateKeyError, loads_no_duplicates
from project_context import enforce_facade_project
from session_contract import load_static_session, read_regular_bytes
from transaction_utils import exclusive_lock

# characters whose OCR confusion is not a typo in practice (long vowel marks, dashes, small kana size)
FOLD = str.maketrans(
    {
        "ー": "-", "－": "-", "―": "-", "—": "-", "‐": "-", "〜": "~", "～": "~",
        "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "っ": "つ",
        "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ッ": "ツ",
    }
)
WHITESPACE = re.compile(r"[\s\u3000]+")
LOOSE_STRIP = re.compile(r"[!！?？。、.,、・「」『』()（）\[\]【】\"'…♪★☆♡♥]+")


def normalize(text: str, loose: bool) -> str:
    # OCR inserts layout whitespace unpredictably, so both modes ignore it. Strict
    # comparison still preserves symbols, compatibility-width differences, and case.
    text = unicodedata.normalize("NFKC" if loose else "NFC", text)
    text = WHITESPACE.sub("", text)
    if loose:
        text = LOOSE_STRIP.sub("", text)
        text = text.translate(FOLD)
        return text.lower()
    return text


def checked_project_paths(
    manifest_value: str, stamp_value: str, review_value: str
) -> tuple[Path, Path, Path]:
    """Bind OCR inputs and versioned reports to the active project."""
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
        raise ValueError("projects/ACTIVE must be a regular non-symlink file during text verification")
    try:
        active = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read projects/ACTIVE as UTF-8: {exc}") from exc
    if active != project_dir.name:
        raise ValueError(
            f"projects/ACTIVE={active!r} does not select text-verification project {project_dir.name!r}"
        )
    return manifest, stamps, review


def ocr_available(lang: str) -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "pytesseract がインストールされていない（pip install pytesseract、tesseract 本体も必要）"
    try:
        import pytesseract

        langs = pytesseract.get_languages(config="")
    except Exception as exc:  # tesseract binary missing
        return False, f"tesseract を実行できない: {exc}"
    missing = [part for part in lang.split("+") if part not in langs]
    if missing:
        return False, f"tesseract 言語データが不足: {missing}（jpn.traineddata を tessdata へ配置）"
    return True, ""


def prepare(image: Image.Image, scale: int) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(white, rgba).convert("L")
    flat = ImageOps.autocontrast(flat)
    if scale > 1:
        flat = flat.resize((flat.width * scale, flat.height * scale), Image.Resampling.LANCZOS)
    return flat


def run_ocr(image: Image.Image, lang: str, scale: int) -> str:
    import pytesseract

    best = ""
    for psm in (6, 7, 11):
        text = pytesseract.image_to_string(prepare(image, scale), lang=lang, config=f"--psm {psm}")
        text = text.strip()
        if len(text) > len(best):
            best = text
    return best


def next_version(review_dir: Path) -> int:
    versions = [
        int(match.group(1))
        for path in review_dir.glob("text-check-v*.*")
        if (match := re.fullmatch(r"text-check-v(\d+)\.(?:md|json)", path.name))
    ]
    return max(versions, default=0) + 1


def verification_session(project_dir: Path) -> tuple[dict[str, str], list[str]]:
    """Read the gate/count contract that defines P4 versus complete P5 evidence."""
    try:
        values = load_static_session(project_dir, {"P4", "P5"})
    except ValueError as exc:
        return {}, [str(exc)]
    errors: list[str] = []
    if values.get("text") != "yes" or values.get("text_mode") != "ai":
        errors.append("verify-text requires SESSION text=yes and text_mode=ai")
    return values, errors


def verification_scope(
    session: dict[str, str],
    manifest_ids: set[int],
    requested_ids: set[int] | None,
) -> set[int]:
    """Bind sample and final OCR evidence to their exact gate/count semantics."""
    count = int(session["count"])
    expected_ids = set(range(1, count + 1))
    out_of_range = sorted(manifest_ids - expected_ids)
    if out_of_range:
        raise ValueError(f"manifest ids exceed SESSION count: {out_of_range}")
    if session["gate"] == "P4":
        if requested_ids != {1} or 1 not in manifest_ids:
            raise ValueError("P4 requires --only 1 and a manifest item for stamp01")
        return {1}
    if manifest_ids != expected_ids:
        missing_ids = sorted(expected_ids - manifest_ids)
        raise ValueError(
            "P5 requires manifest ids exactly 1..SESSION count; "
            f"missing={missing_ids} extra={out_of_range}"
        )
    if requested_ids is not None:
        raise ValueError("P5 final evidence must recheck every id; omit --only")
    return expected_ids


def write_report_pair(md_path: Path, md_text: str, json_path: Path, json_text: str) -> None:
    """Create both versioned reports without overwriting and clean up caught partial writes."""
    created: list[tuple[Path, os.stat_result]] = []
    try:
        for path, payload in (
            (md_path, md_text.encode("utf-8")),
            (json_path, json_text.encode("utf-8")),
        ):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR-check AI-drawn stamp text against the approved manifest lines")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dir", required=True, help="directory holding stampNN.png (raw/, characters/ or stamps/)")
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--lang", default="jpn+eng")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--only", help="comma-separated stamp ids to check (e.g. 1 or 3,7)")
    parser.add_argument("--min-similarity", type=float, default=0.85, help="below this a line is reported as mismatch even in loose mode")
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
    except ValueError as exc:
        print(f"ERROR verify-text: {exc}")
        return 1
    session, session_errors = verification_session(manifest_path.parent)
    if session_errors:
        for message in session_errors:
            print(f"ERROR verify-text: {message}")
        return 1
    try:
        manifest_payload = read_regular_bytes(manifest_path)
        manifest = loads_no_duplicates(manifest_payload.decode("utf-8"))
        manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR verify-text: manifest を読めない: {exc}")
        return 1
    if not isinstance(manifest, dict):
        print("ERROR verify-text: manifest のルートはオブジェクトでなければならない")
        return 1
    manifest_items = manifest.get("items")
    if not isinstance(manifest_items, list) or not manifest_items:
        print("ERROR verify-text: manifest.items がない、または空のため検査対象を選べない")
        return 1

    items_by_id: dict[int, dict] = {}
    for position, item in enumerate(manifest_items, start=1):
        if not isinstance(item, dict) or "id" not in item:
            print(f"ERROR verify-text: manifest.items[{position}] に id がない")
            return 1
        item_id = item["id"]
        if type(item_id) is not int or item_id not in range(1, 41):
            print(f"ERROR verify-text: manifest.items[{position}].id は1〜40の整数でなければならない")
            return 1
        if item_id in items_by_id:
            print(f"ERROR verify-text: manifest.items に id={item_id} が重複している")
            return 1
        items_by_id[item_id] = item

    manifest_ids = set(items_by_id)

    if args.only is None:
        requested_ids = None
    else:
        tokens = [part.strip() for part in args.only.split(",")]
        if not tokens or any(not token for token in tokens):
            print("ERROR verify-text: --only には1つ以上の stamp id をカンマ区切りで指定する")
            return 1
        try:
            requested_list = [int(token) for token in tokens]
        except ValueError:
            print("ERROR verify-text: --only の stamp id は整数で指定する")
            return 1
        if any(item_id not in range(1, 41) for item_id in requested_list):
            print("ERROR verify-text: --only の stamp id は1〜40で指定する")
            return 1
        if len(requested_list) != len(set(requested_list)):
            print("ERROR verify-text: --only の stamp id を重複させない")
            return 1
        requested_ids = set(requested_list)
        absent_ids = sorted(requested_ids - items_by_id.keys())
        if absent_ids:
            formatted = ", ".join(str(item_id) for item_id in absent_ids)
            print(f"ERROR verify-text: --only の id が manifest.items にない: {formatted}")
            return 1
    try:
        selected_ids = verification_scope(session, manifest_ids, requested_ids)
    except ValueError as exc:
        print(f"ERROR verify-text: {exc}")
        return 1
    items = [item for item in manifest_items if int(item["id"]) in selected_ids]
    if not items:
        print("ERROR verify-text: 検査対象が空。manifest.items または --only を確認する")
        return 1

    review_dir.mkdir(parents=True, exist_ok=True)

    available, reason = ocr_available(args.lang)
    rows: list[dict] = []
    for item in items:
        index = int(item["id"])
        text_value = item.get("text")
        text_valid = isinstance(text_value, str) or (
            isinstance(text_value, list) and all(isinstance(line, str) for line in text_value)
        )
        if isinstance(text_value, str):
            expected = text_value
        elif isinstance(text_value, list) and text_valid:
            expected = "".join(text_value)
        else:
            expected = ""
        path = stamp_dir / f"stamp{index:02d}.png"
        row = {
            "id": index,
            "file": path.name,
            "sha256": None,
            "expected": expected,
            "ocr": "",
            "status": "",
            "similarity": None,
        }
        if not text_valid or not normalize(expected, False):
            row["status"] = "manifest-invalid"
        elif path.is_symlink() or not path.is_file():
            row["status"] = "missing"
        else:
            try:
                stamp_payload = read_regular_bytes(path)
                row["sha256"] = hashlib.sha256(stamp_payload).hexdigest()
                if not available:
                    row["status"] = "visual-required"
                else:
                    with Image.open(io.BytesIO(stamp_payload)) as opened:
                        opened.load()
                        ocr = run_ocr(opened, args.lang, args.scale)
                    row["ocr"] = ocr.replace("\n", "/")
                    strict = normalize(expected, False) == normalize(ocr, False)
                    loose_e, loose_o = normalize(expected, True), normalize(ocr, True)
                    similarity = difflib.SequenceMatcher(None, loose_e, loose_o).ratio() if loose_e else 0.0
                    row["similarity"] = round(similarity, 3)
                    if strict:
                        row["status"] = "match"
                    elif loose_e == loose_o or similarity >= args.min_similarity:
                        row["status"] = "near"  # likely OCR noise; must be confirmed visually
                    else:
                        row["status"] = "mismatch"
            except (OSError, ValueError, RuntimeError):
                row["status"] = "unreadable"
        rows.append(row)

    mismatches = [r for r in rows if r["status"] == "mismatch"]
    missing = [r for r in rows if r["status"] == "missing"]
    unreadable = [r for r in rows if r["status"] == "unreadable"]
    invalid = [r for r in rows if r["status"] == "manifest-invalid"]
    near = [r for r in rows if r["status"] == "near"]
    visual = [r for r in rows if r["status"] == "visual-required"]

    with exclusive_lock(review_dir / ".line-stamp-verify.lock", "verify-text report transaction"):
        version = next_version(review_dir)
        md_path = review_dir / f"text-check-v{version:02d}.md"
        json_path = review_dir / f"text-check-v{version:02d}.json"
        scope = "sample" if session["gate"] == "P4" else "all"
        lines_md = [f"# text-check v{version:02d}", "", f"- project: `{manifest_path.parent.name}`", f"- gate: `{session['gate']}`", f"- scope: `{scope}`", f"- dir: `{args.dir}`", f"- lang: `{args.lang}`", f"- ocr: {'available' if available else 'unavailable — ' + reason}", "",
                    "| id | expected | ocr | similarity | status |", "|---|---|---|---|---|"]
        for r in rows:
            sim = "" if r["similarity"] is None else f"{r['similarity']:.2f}"
            expected_cell = str(r["expected"]).replace("|", "\\|").replace("\n", "<br>")
            ocr_cell = str(r["ocr"]).replace("|", "\\|").replace("\n", "<br>")
            lines_md.append(f"| {r['id']:02d} | {expected_cell} | {ocr_cell} | {sim} | {r['status']} |")
        lines_md += ["", "## 次にやること", "",
                     "- `manifest-invalid`: manifest の空または不正な `text` を修正して再検査する",
                     "- `missing`: 対象画像を用意して再検査する",
                     "- `unreadable`: 読み取れない対象画像を修復して再検査する",
                     "- `mismatch`: OCR 単独では再生成しない。エージェントの読み取りとユーザーの目視で実画像の不一致を確認した番号だけ再生成する",
                     "- `near`: OCR ノイズの可能性。エージェントが画像を読み、ユーザーに目視確認を取る",
                     "- `visual-required`: OCR 不可。全点をエージェントが読み上げ、ユーザーの目視承認で判定する",
                     "- OCR の結果だけで合否、再生成、SESSION `text_check: ok` を決めない。ユーザーの承認が必須", ""]
        json_text = json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "project": manifest_path.parent.name,
                "gate": session["gate"],
                "scope": scope,
                "session_count": int(session["count"]),
                "manifest_sha256": manifest_sha256,
                "ocr_available": available,
                "reason": reason,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
        write_report_pair(md_path, "\n".join(lines_md), json_path, json_text)

    print(f"text-check v{version:02d}: checked={len(rows)} match={sum(r['status']=='match' for r in rows)} near={len(near)} mismatch={len(mismatches)} missing={len(missing)} unreadable={len(unreadable)} manifest-invalid={len(invalid)} visual-required={len(visual)}")
    for r in invalid + missing + unreadable + mismatches + near:
        print(f"{r['status'].upper()} stamp{r['id']:02d}: expected='{r['expected']}' ocr='{r['ocr']}'")
    print(f"report: {md_path}")
    input_issues = invalid + missing + unreadable
    if input_issues:
        return 1
    if not available:
        print(f"OCR unavailable: {reason} — 全点を目視で確認する")
        return 2
    return 1 if mismatches or near else 0


if __name__ == "__main__":
    raise SystemExit(main())
