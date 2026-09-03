#!/usr/bin/env python3
"""Verify that AI-drawn text in stamp images matches the approved lines in the manifest.

Used only when SESSION text_mode=ai. Runs OCR on each image, normalizes both sides, and writes
review/text-check-vNN.md (+ .json). OCR is a first pass only: the agent must still read every image
and the user must approve before SESSION text_check becomes ok.

Exit codes: 0 all matched / 1 at least one mismatch / 2 OCR unavailable (visual check required)
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps

# characters whose OCR confusion is not a typo in practice (long vowel marks, dashes, small kana size)
FOLD = str.maketrans(
    {
        "ー": "-", "－": "-", "―": "-", "—": "-", "‐": "-", "〜": "~", "～": "~",
        "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "っ": "つ",
        "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ッ": "ツ",
    }
)
STRIP = re.compile(r"[\s\u3000!！?？。、.,、・「」『』()（）\[\]【】\"'…♪★☆♡♥]+")


def normalize(text: str, loose: bool) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = STRIP.sub("", text)
    if loose:
        text = text.translate(FOLD)
    return text.lower()


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
    versions = [int(m.group(1)) for p in review_dir.glob("text-check-v*.md") if (m := re.search(r"v(\d+)\.md$", p.name))]
    return max(versions, default=0) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR-check AI-drawn stamp text against the approved manifest lines")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dir", required=True, help="directory holding stampNN.png (raw/, characters/ or stamps/)")
    parser.add_argument("--review-dir", default="review")
    parser.add_argument("--lang", default="jpn+eng")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--only", help="comma-separated stamp ids to check (e.g. 1 or 3,7)")
    parser.add_argument("--min-similarity", type=float, default=0.85, help="below this a line is reported as mismatch even in loose mode")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_dir = Path(args.review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    version = next_version(review_dir)
    md_path = review_dir / f"text-check-v{version:02d}.md"
    json_path = review_dir / f"text-check-v{version:02d}.json"

    only = {int(x) for x in args.only.split(",")} if args.only else None
    items = [it for it in manifest["items"] if only is None or int(it["id"]) in only]

    available, reason = ocr_available(args.lang)
    rows: list[dict] = []
    for item in items:
        index = int(item["id"])
        lines = item.get("text", [])
        if isinstance(lines, str):
            lines = lines.split("\n") if lines else []
        expected = "".join(lines)
        path = Path(args.dir) / f"stamp{index:02d}.png"
        row = {"id": index, "file": path.name, "expected": expected, "ocr": "", "status": "", "similarity": None}
        if not path.exists():
            row["status"] = "missing"
        elif not expected:
            row["status"] = "no-text"
        elif not available:
            row["status"] = "visual-required"
        else:
            ocr = run_ocr(Image.open(path), args.lang, args.scale)
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
        rows.append(row)

    mismatches = [r for r in rows if r["status"] in ("mismatch", "missing")]
    near = [r for r in rows if r["status"] == "near"]
    visual = [r for r in rows if r["status"] == "visual-required"]

    lines_md = [f"# text-check v{version:02d}", "", f"- dir: `{args.dir}`", f"- lang: `{args.lang}`", f"- ocr: {'available' if available else 'unavailable — ' + reason}", "",
                "| id | expected | ocr | similarity | status |", "|---|---|---|---|---|"]
    for r in rows:
        sim = "" if r["similarity"] is None else f"{r['similarity']:.2f}"
        lines_md.append(f"| {r['id']:02d} | {r['expected']} | {r['ocr']} | {sim} | {r['status']} |")
    lines_md += ["", "## 次にやること", "",
                 "- `mismatch` `missing`: 該当番号を再生成して再検査する",
                 "- `near`: OCR ノイズの可能性。エージェントが画像を読み、ユーザーに目視確認を取る",
                 "- `visual-required`: OCR 不可。全点をエージェントが読み上げ、ユーザーの目視承認で判定する",
                 "- OCR の結果だけで SESSION `text_check: ok` にしない。ユーザーの承認が必須", ""]
    md_path.write_text("\n".join(lines_md), encoding="utf-8")
    json_path.write_text(json.dumps({"version": version, "ocr_available": available, "reason": reason, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"text-check v{version:02d}: checked={len(rows)} match={sum(r['status']=='match' for r in rows)} near={len(near)} mismatch={len(mismatches)} visual-required={len(visual)}")
    for r in mismatches + near:
        print(f"{r['status'].upper()} stamp{r['id']:02d}: expected='{r['expected']}' ocr='{r['ocr']}'")
    print(f"report: {md_path}")
    if not available:
        print(f"OCR unavailable: {reason} — 全点を目視で確認する")
        return 2
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
