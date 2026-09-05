#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import zipfile
from argparse import ArgumentParser, Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from compose_static import checked_items, checked_output_directories, text_layer_output
from check_publish_ready import (
    check_ai_provenance,
    check_ai_declaration,
    check_boolean,
    check_copyright,
    check_license_proof,
    check_project_layout,
    check_sales_area,
    check_session_state,
    check_store_visibility,
    check_text,
    counted_length,
    has_emoji_or_symbol,
)
from image_utils import (
    add_white_outline,
    enforce_safe_margin,
    fill_small_transparent_holes,
    hidden_rgb_pixels,
    internal_hole_sizes_outside_mask,
    sanitize_alpha,
    save_png,
)
from make_contact_sheet import (
    checked_stamp_files,
    checked_paths as checked_review_paths,
    expected_review_inputs,
)
from metadata_utils import DuplicateKeyError, loads_no_duplicates
from package_static import package_static
from preprocess_character import checked_paths as checked_preprocess_paths
import project as project_module
from project import (
    ProjectPathError,
    atomic_write_text,
    cmd_confirm_p0,
    cmd_complete_production,
    cmd_confirm_account,
    cmd_confirm_design,
    cmd_confirm_three_view,
    cmd_migrate,
    cmd_new,
    cmd_record_learning,
    cmd_use,
    migrated_submission,
    parse_session_for_migration,
    p0_updates,
    project_directory,
    projects_root,
    remove_session_keys,
    session_migration_updates,
    update_session_text,
    valid_slug,
)
from project_context import FACADE_PROJECT_ENV, enforce_facade_project
from session_contract import (
    load_static_session,
    project_stamp_name,
    require_complete_text_evidence,
    require_review_evidence,
    sha256_file,
    submission_stamp_name,
    visual_text_matches,
)
from validate_pack import (
    validate_png,
    validate_submission_names,
    validate_stamp_sources,
    validate_zip,
)
from text_evidence import (
    load_visual_review,
    next_version,
    text_region,
    verification_scope,
    verification_session,
)
import transaction_utils
import text_evidence
import make_contact_sheet


def check_visual_review_flow() -> None:
    """Exercise observation recording and rejection without any recognition service."""
    assert visual_text_matches("ありがとう", "ありがと\nう")
    assert visual_text_matches("が", "か\u3099")
    assert not visual_text_matches("ありがとう", "ありがどう")
    assert not visual_text_matches("おはよう！", "おはよう!")
    assert not visual_text_matches("おはよう", "")
    assert text_evidence.markdown_cell("A|B\n<script>") == "A&#124;B<br>&lt;script&gt;"
    with TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "projects" / "visual-demo"
        for name in ("stamps", "review", "meta"):
            (project / name).mkdir(parents=True)
        (root / "projects" / "ACTIVE").write_text("visual-demo\n", encoding="utf-8")
        session_path = project / "SESSION.md"
        session_path.write_text(
            "- schema_version: 4\n- project: visual-demo\n- materials: received\n"
            "- count: 8\n- text: yes\n- text_mode: ai\n- text_check: not-run\n"
            "- text_mask_version: 0\n- review_version: 0\n- gate: P4\n",
            encoding="utf-8",
        )
        write_design_evidence_fixture(project)
        p4_session = session_path.read_text(encoding="utf-8")
        manifest_path = project / "manifest.json"
        manifest = {"items": []}
        for index in range(1, 9):
            stamp = Image.new("RGBA", (160, 120), (0, 0, 0, 0))
            draw = ImageDraw.Draw(stamp)
            draw.text((20, 20), f"Hello {index}!", fill="black")
            draw.ellipse((48, 45, 100, 97), fill=(80, 160, 200, 255))
            stamp.save(project / "stamps" / f"stamp{index:02d}.png", dpi=(72, 72))
            manifest["items"].append({
                "id": index, "text": f"Hello {index}!", "text_region": [18, 18, 100, 35],
            })
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        observations = {
            "schema_version": 1, "method": "ai-visual",
            "manifest_sha256": sha256_file(manifest_path),
            "items": [{
                "id": index, "file": f"stamp{index:02d}.png",
                "sha256": sha256_file(project / "stamps" / f"stamp{index:02d}.png"),
                "expected": f"Hello {index}!", "recognized": f"Hello {index}!", "status": "match",
            } for index in range(1, 9)],
        }
        input_path = project / "review" / "visual-reading.json"

        def record(payload: dict, *, sample: bool = False) -> int:
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            previous = sys.argv
            sys.argv = ["verify-text", "--manifest", str(manifest_path), "--dir",
                        str(project / "stamps"), "--review-dir", str(project / "review"),
                        "--visual-review", str(input_path)] + (["--only", "1"] if sample else [])
            try:
                with redirect_stdout(StringIO()):
                    return text_evidence.run()
            finally:
                sys.argv = previous

        def require_rejection(version: int) -> None:
            try:
                require_complete_text_evidence(project, 8, version)
            except ValueError:
                pass
            else:
                raise AssertionError("incomplete or changed visual review passed P6")

        assert record(dict(observations, items=observations["items"][:1]), sample=True) == 0
        sample_report = project / "review" / "text-check-v01.json"
        sample_bytes = sample_report.read_bytes()
        assert json.loads(sample_bytes)["scope"] == "sample"
        require_rejection(1)
        p5_session = p4_session.replace("- gate: P4", "- gate: P5")
        session_path.write_text(p5_session, encoding="utf-8")
        assert record(observations) == 0
        require_complete_text_evidence(project, 8, 2)
        assert sample_report.read_bytes() == sample_bytes
        report_path = project / "review" / "text-check-v02.json"
        valid_report = report_path.read_bytes()
        report = json.loads(valid_report)
        assert report["schema_version"] == 3 and report["method"] == "ai-visual"
        assert not any(key.startswith("automatic_") for key in report)
        assert "AI reading" in report_path.with_suffix(".md").read_text(encoding="utf-8")

        # P5 approval and the actual contact sheet still bind every current image.
        previous = sys.argv
        sys.argv = ["make-contact-sheet", "--input", str(project / "stamps"),
                    "--output", str(project / "review" / "review-v01.png")]
        try:
            with redirect_stdout(StringIO()):
                make_contact_sheet.main()
        finally:
            sys.argv = previous
        approved = p5_session.replace("- gate: P5", "- gate: P6").replace(
            "- text_check: not-run", "- text_check: ok"
        ).replace("- text_mask_version: 0", "- text_mask_version: 2").replace(
            "- review_version: 0", "- review_version: 1"
        )
        session_path.write_text(approved, encoding="utf-8")
        assert load_static_session(project, {"P6"})["text_check"] == "ok"
        session_path.write_text(p5_session, encoding="utf-8")

        # Report edits cannot turn a different reading or expected phrase into a match.
        for field, value in (("recognized", "Hello 1?"), ("expected", "Hello 9!"),
                             ("status", "unreadable"), ("status", "not-run")):
            changed = json.loads(valid_report)
            changed["rows"][0][field] = value
            report_path.write_text(json.dumps(changed), encoding="utf-8")
            require_rejection(2)
        report_path.write_bytes(valid_report)
        original_manifest = manifest_path.read_bytes()
        manifest_path.write_bytes(original_manifest + b" ")
        require_rejection(2)
        assert record(observations) == 1
        manifest_path.write_bytes(original_manifest)
        mask_path = project / report["rows"][0]["mask_file"]
        mask_bytes = mask_path.read_bytes()
        mask_path.write_bytes(b"changed mask")
        require_rejection(2)
        mask_path.write_bytes(mask_bytes)

        # Missing observations never create a new report or silently use an older one.
        before = next_version(project / "review")
        assert record(dict(observations, items=observations["items"][:1])) == 1
        assert record(dict(observations, items=observations["items"] + observations["items"][:1])) == 1
        assert record(dict(observations, method="ocr")) == 1
        assert next_version(project / "review") == before
        for status in ("not-run", "unreadable", "mismatch"):
            changed = json.loads(json.dumps(observations))
            changed["items"][0]["status"] = status
            version = next_version(project / "review")
            assert record(changed) == 1
            require_rejection(version)
        changed = json.loads(json.dumps(observations))
        changed["items"][0]["recognized"] = "Hello 1?"
        version = next_version(project / "review")
        assert record(changed) == 1  # A claimed match cannot hide changed punctuation.
        require_rejection(version)

        # A new image requires a fresh observation; previous versions remain immutable.
        stamp_path = project / "stamps" / "stamp01.png"
        with Image.open(stamp_path) as opened:
            changed_stamp = opened.convert("RGBA")
        changed_stamp.putpixel((60, 60), (255, 0, 0, 255))
        changed_stamp.save(stamp_path, dpi=(72, 72))
        assert record(observations) == 1
        observations["items"][0]["sha256"] = sha256_file(stamp_path)
        version = next_version(project / "review")
        assert record(observations) == 0
        require_complete_text_evidence(project, 8, version)
        assert report_path.read_bytes() == valid_report

        # Record-path and approval boundaries remain intact.
        foreign = root / "foreign.json"
        foreign.write_text(json.dumps(observations), encoding="utf-8")
        try:
            load_visual_review(str(foreign), project, sha256_file(manifest_path), set(range(1, 9)))
        except ValueError:
            pass
        else:
            raise AssertionError("visual observations escaped the project")
        for mode in ("font", "none"):
            session_path.write_text(p5_session.replace("- text_mode: ai", f"- text_mode: {mode}").replace(
                "- text_check: not-run", "- text_check: n/a"
            ).replace("- text: yes", "- text: no" if mode == "none" else "- text: yes"), encoding="utf-8")
            assert record(observations) == 1


def write_review_evidence_fixture(project: Path, count: int, version: int = 1) -> None:
    """Create a compact but structurally real P5 review evidence pair for tests."""
    review_dir = project / "review"
    review_dir.mkdir(exist_ok=True)
    image_path = review_dir / f"review-v{version:02d}.png"
    if not image_path.exists():
        image_path.write_bytes(b"review fixture")
    evidence = {
        "schema_version": 1,
        "version": version,
        "project": project.name,
        "gate": "P5",
        "presentation": "all-stamps-light-dark",
        "session_count": count,
        "review_file": image_path.name,
        "review_sha256": sha256_file(image_path),
        "stamps": [
            {
                "id": index,
                "file": f"stamp{index:02d}.png",
                "sha256": sha256_file(project / "stamps" / f"stamp{index:02d}.png"),
            }
            for index in range(1, count + 1)
        ],
    }
    (review_dir / f"review-v{version:02d}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_design_evidence_fixture(project: Path) -> None:
    """Create P1/P2 evidence and bind the fixture SESSION to it."""
    refs = project / "refs"
    refs.mkdir(exist_ok=True)
    source = refs / "source.png"
    design = refs / "design-v01.png"
    three_view = refs / "three-view-v01.png"
    for path, color in (
        (source, (60, 80, 100, 255)),
        (design, (80, 100, 120, 255)),
        (three_view, (100, 120, 140, 255)),
    ):
        save_png(Image.new("RGBA", (80, 80), color), path)
    spec = refs / "design-v01.md"
    spec.write_text("# Design v01\n\nfixture\n", encoding="utf-8")
    design_evidence = {
        "schema_version": 1,
        "version": 1,
        "project": project.name,
        "gate": "P1",
        "checklist": {
            "hairstyle": "short",
            "head_ratio": 2.2,
            "clothing": "blue jacket",
            "palette": ["#1A2B3C", "#F4D7C5"],
            "eyes": "round",
            "accessories": "none",
            "background": "transparent",
        },
        "design_file": "refs/design-v01.png",
        "design_sha256": sha256_file(design),
        "spec_file": "refs/design-v01.md",
        "spec_sha256": sha256_file(spec),
        "references": [
            {"file": "refs/source.png", "sha256": sha256_file(source)}
        ],
    }
    evidence_path = refs / "design-v01.json"
    evidence_path.write_text(
        json.dumps(design_evidence, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    three_evidence = {
        "schema_version": 1,
        "version": 1,
        "project": project.name,
        "gate": "P2",
        "three_view_file": "refs/three-view-v01.png",
        "three_view_sha256": sha256_file(three_view),
        "design_evidence": "refs/design-v01.json",
        "design_evidence_sha256": sha256_file(evidence_path),
    }
    (refs / "three-view-v01.json").write_text(
        json.dumps(three_evidence, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    session = project / "SESSION.md"
    session.write_text(
        update_session_text(
            session.read_text(encoding="utf-8"),
            {
                "design_version": "1",
                "design_evidence": "refs/design-v01.json",
                "lock": "approved",
                "three_view": "approved",
                "three_view_version": "1",
            },
        ),
        encoding="utf-8",
    )


def main() -> None:
    assert [project_stamp_name(index) for index in (1, 8, 40)] == [
        "stamp01.png",
        "stamp08.png",
        "stamp40.png",
    ]
    assert [submission_stamp_name(index) for index in (1, 8, 40)] == [
        "01.png",
        "08.png",
        "40.png",
    ]
    for invalid_index in (True, 0, 41):
        for naming_function in (project_stamp_name, submission_stamp_name):
            try:
                naming_function(invalid_index)
            except ValueError:
                pass
            else:
                raise AssertionError(f"stamp naming accepted invalid index {invalid_index!r}")

    assert text_layer_output("font", "text-layers") == Path("text-layers")
    assert text_layer_output("ai", None) is None
    assert text_layer_output("none", None) is None
    for mode, value in (("font", None), ("ai", "text-layers"), ("none", "text-layers")):
        try:
            text_layer_output(mode, value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid text layer output accepted: {mode=} {value=}")

    parser = ArgumentParser(description="Run line-stamp harness regression tests")
    parser.parse_args()
    if not __debug__:
        raise RuntimeError("self-test requires assertions; rerun Python without -O/PYTHONOPTIMIZE")

    with TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "target"
        target.mkdir()
        try:
            (root / "projects").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            try:
                projects_root(str(root))
            except ProjectPathError:
                pass
            else:
                raise AssertionError("project CLI accepted a symlinked projects directory")

    assert counted_length("abc") == 3
    assert counted_length("あいう") == 6
    assert counted_length("Aあ") == 3
    assert not has_emoji_or_symbol("𠮷野家")
    assert has_emoji_or_symbol("笑顔😀")
    assert has_emoji_or_symbol("1\ufe0f\u20e3")

    text_errors: list[str] = []
    check_text("sample", "猫ＬＩＮＥスタンプ", (1, 50), False, text_errors)
    assert any("LINE" in message for message in text_errors)
    url_errors: list[str] = []
    check_text("sample", "example.com", (1, 50), False, url_errors)
    assert any("URL" in message for message in url_errors)
    invisible_errors: list[str] = []
    check_text("sample", "L\u200bINE Stickers", (1, 50), False, invisible_errors)
    assert any("invisible or control" in message for message in invisible_errors)
    sales_errors: list[str] = []
    check_sales_area({"sales_area": "all", "sales_countries": []}, sales_errors)
    assert not sales_errors
    check_sales_area({"sales_area": "some", "sales_countries": []}, sales_errors)
    assert sales_errors
    malformed_sales_errors: list[str] = []
    check_sales_area({"sales_area": [], "sales_countries": []}, malformed_sales_errors)
    assert malformed_sales_errors
    boolean_errors: list[str] = []
    assert check_boolean({"ai_used": 1}, "ai_used", boolean_errors) is None
    assert boolean_errors
    with TemporaryDirectory() as directory:
        project_dir = Path(directory)
        (project_dir / "refs").mkdir()
        proof_errors: list[str] = []
        check_license_proof({}, project_dir, proof_errors)
        assert not proof_errors
        check_license_proof(
            {"license_proof": {"status": "not-required", "reference": ""}},
            project_dir,
            proof_errors,
        )
        assert not proof_errors
        licensed_errors: list[str] = []
        check_license_proof(
            {"license_proof": {"status": "user-confirmed", "reference": "missing.txt"}},
            project_dir,
            licensed_errors,
        )
        assert licensed_errors
        (project_dir / "refs" / "license.txt").write_bytes(b"")
        empty_license_errors: list[str] = []
        check_license_proof(
            {"license_proof": {"status": "user-confirmed", "reference": "refs/license.txt"}},
            project_dir,
            empty_license_errors,
        )
        assert any("must not be empty" in message for message in empty_license_errors)
        (project_dir / "refs" / "license.txt").write_text("confirmed", encoding="utf-8")
        licensed_errors = []
        check_license_proof(
            {"license_proof": {"status": "user-confirmed", "reference": "refs/license.txt"}},
            project_dir,
            licensed_errors,
        )
        assert not licensed_errors
        traversal_errors: list[str] = []
        check_license_proof(
            {"license_proof": {"status": "user-confirmed", "reference": "../outside.txt"}},
            project_dir,
            traversal_errors,
        )
        assert traversal_errors
        malformed_license_errors: list[str] = []
        check_license_proof(
            {"license_proof": {"status": [], "reference": ""}},
            project_dir,
            malformed_license_errors,
        )
        assert malformed_license_errors
        provenance_errors: list[str] = []
        check_ai_provenance(project_dir, True, provenance_errors)
        assert provenance_errors
        (project_dir / "meta").mkdir()
        (project_dir / "meta" / "ai-provenance.md").write_text("# Provenance\n", encoding="utf-8")
        provenance_errors = []
        check_ai_provenance(project_dir, True, provenance_errors)
        assert provenance_errors
        prompt_path = project_dir / "meta" / "approved-prompt.txt"
        prompt_path.write_text("approved prompt for the generated stamp images\n", encoding="utf-8")
        (project_dir / "meta" / "ai-provenance.md").write_text(
            "# AI provenance\n\n"
            "- ai_used: true\n"
            "- scope: character-design, stamp-images\n"
            "- tool_and_model: ExampleTool ExampleModel\n"
            "- generated_at: 2000-01-01\n"
            "- prompt_reference: meta/approved-prompt.txt\n"
            "- reviewed_by_user_at_gate: P2, P5\n",
            encoding="utf-8",
        )
        provenance_errors = []
        check_ai_provenance(project_dir, True, provenance_errors)
        assert not provenance_errors
        missing_text_scope_errors: list[str] = []
        check_ai_provenance(project_dir, True, missing_text_scope_errors, {"text"})
        assert any("missing required" in message for message in missing_text_scope_errors)
        (project_dir / "meta" / "ai-provenance.md").write_text(
            (project_dir / "meta" / "ai-provenance.md")
            .read_text(encoding="utf-8")
            .replace("scope: character-design, stamp-images", "scope: character-design, stamp-images, text"),
            encoding="utf-8",
        )
        complete_text_scope_errors: list[str] = []
        check_ai_provenance(project_dir, True, complete_text_scope_errors, {"text"})
        assert not complete_text_scope_errors
        provenance_path = project_dir / "meta" / "ai-provenance.md"
        complete_provenance = provenance_path.read_text(encoding="utf-8")
        provenance_path.write_text(
            complete_provenance.replace(
                "prompt_reference: meta/approved-prompt.txt",
                "prompt_reference: meta/ai-provenance.md",
            ),
            encoding="utf-8",
        )
        self_reference_errors: list[str] = []
        check_ai_provenance(project_dir, True, self_reference_errors, {"text"})
        assert any("must not refer" in message for message in self_reference_errors)
        provenance_path.write_text(
            "# AI provenance\n\n"
            "## Prompt or reproducibility note\n"
            "- ai_used: true\n"
            "- scope: character-design, stamp-images, text\n"
            "- tool_and_model: ExampleTool ExampleModel\n"
            "- generated_at: 2000-01-01\n"
            "- prompt_reference: inline below\n"
            "- reviewed_by_user_at_gate: P2, P5\n"
            "concrete prompt text\n",
            encoding="utf-8",
        )
        inline_order_errors: list[str] = []
        check_ai_provenance(project_dir, True, inline_order_errors, {"text"})
        assert any("before the prompt note heading" in message for message in inline_order_errors)
        provenance_path.write_text(complete_provenance, encoding="utf-8")
        prompt_path.write_text("", encoding="utf-8")
        empty_prompt_errors: list[str] = []
        check_ai_provenance(project_dir, True, empty_prompt_errors)
        assert any("must not be empty" in message for message in empty_prompt_errors)

    complete_session = {
        "schema_version": "4",
        "project": "demo",
        "materials": "received",
        "source": "character",
        "count": "16",
        "text": "yes",
        "text_mode": "font",
        "text_check": "n/a",
        "text_mask_version": "0",
        "gate": "P7",
        "character": "Hatch",
        "publish": "yes",
        "validation": "ok",
        "review_version": "1",
        "design_version": "1",
        "design_evidence": "refs/design-v01.json",
        "three_view": "approved",
        "three_view_version": "1",
        "submission": "not-started",
    }
    session_errors: list[str] = []
    check_session_state(complete_session, Path("projects/demo/SESSION.md"), session_errors)
    assert not session_errors
    deprecated_session_errors: list[str] = []
    check_session_state(
        dict(complete_session, consent="yes"),
        Path("projects/demo/SESSION.md"),
        deprecated_session_errors,
    )
    assert any("deprecated fields" in message for message in deprecated_session_errors)
    incomplete_session_errors: list[str] = []
    check_session_state(
        {key: value for key, value in complete_session.items() if key != "count"},
        Path("projects/demo/SESSION.md"),
        incomplete_session_errors,
    )
    assert any("count" in message for message in incomplete_session_errors)
    oversized_count_errors: list[str] = []
    check_session_state(
        dict(complete_session, count="9" * 5000),
        Path("projects/demo/SESSION.md"),
        oversized_count_errors,
    )
    assert oversized_count_errors

    for old_publish, expected in {
        "yes": "yes",
        "no": "local-only",
        "private": "local-only",
        "unknown": "unknown",
    }.items():
        updates, errors = session_migration_updates({"publish": old_publish, "gate": "P0"})
        assert not errors
        assert updates["schema_version"] == "4"
        assert updates["materials"] == "pending"
        assert updates.get("publish", old_publish) == expected
    _, errors = session_migration_updates({"publish": "surprise", "gate": "P0"})
    assert errors
    _, errors = session_migration_updates(
        {"schema_version": "4", "publish": "yes", "materials": "received"}
    )
    assert errors
    pending_legacy = {
        "schema_version": "1",
        "publish": "yes",
        "gate": "P4",
        "materials": "pending",
    }
    _, errors = session_migration_updates(pending_legacy, materials_available=False)
    assert errors
    updates, errors = session_migration_updates(pending_legacy, materials_available=True)
    assert not errors and updates["materials"] == "received"
    updates, errors = session_migration_updates(
        {"schema_version": "02", "publish": "yes", "materials": "received", "gate": "P0"}
    )
    assert not errors and updates["schema_version"] == "4"
    updates, errors = session_migration_updates(
        {
            "schema_version": "3",
            "publish": "yes",
            "materials": "received",
            "gate": "P9",
            "submission": "approved",
            "notes": "legacy",
        }
    )
    assert not errors
    assert updates["gate"] == "P8"
    assert updates["submission"] == "production-complete"
    assert "pre-v4 submission status was approved" in updates["notes"]

    old_session = (
        "# SESSION\n\n- project: sample\n- publish: private\n- gate: P6\n"
        "- rights: own\n- adult: yes\n- consent: yes\n- notes: keep me\n"
    )
    parsed, errors = parse_session_for_migration(old_session)
    assert not errors
    updates, errors = session_migration_updates(parsed, materials_available=True)
    assert not errors
    migrated_session = remove_session_keys(
        update_session_text(old_session, updates), {"adult", "consent", "rights"}
    )
    assert "- schema_version: 4" in migrated_session
    assert "- publish: local-only" in migrated_session
    assert "- materials: received" in migrated_session
    assert not any(
        f"- {key}:" in migrated_session for key in ("adult", "consent", "rights")
    )
    assert "- gate: P6" in migrated_session and "- notes: keep me" in migrated_session
    _, duplicate_errors = parse_session_for_migration("- publish: yes\n- publish: no\n")
    assert duplicate_errors
    try:
        loads_no_duplicates('{"title": 1, "title": 2}')
    except DuplicateKeyError:
        pass
    else:
        raise AssertionError("duplicate JSON key was accepted")
    for non_finite in ("NaN", "Infinity", "-Infinity", "1e9999"):
        try:
            loads_no_duplicates(f'{{"value": {non_finite}}}')
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError(f"non-standard JSON number was accepted: {non_finite}")
    try:
        loads_no_duplicates('{"value": ' + ("9" * 1001) + "}")
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("oversized JSON integer was accepted")

    visibility_errors: list[str] = []
    check_store_visibility(
        {"store_visibility": "public", "private": True}, visibility_errors
    )
    assert visibility_errors
    ai_declaration_errors: list[str] = []
    check_ai_declaration({"text_mode": "ai"}, False, ai_declaration_errors)
    assert ai_declaration_errors
    ai_declaration_errors = []
    check_ai_declaration({"text_mode": "font"}, False, ai_declaration_errors)
    assert not ai_declaration_errors
    copyright_errors: list[str] = []
    check_copyright("2026LINE", copyright_errors)
    assert copyright_errors

    migrated_meta, changes, errors = migrated_submission(
        {
            "private": False,
            "license_proof": {"status": "not-required", "reference": ""},
        }
    )
    assert not errors and changes
    assert migrated_meta["schema_version"] == 3
    assert migrated_meta["sales_start"] == "manual"
    assert migrated_meta["price_confirmed"] is False
    assert migrated_meta["store_visibility"] == "public" and "private" not in migrated_meta
    assert "license_proof" not in migrated_meta
    canonical_meta = {
        "schema_version": 3,
        "sales_start": "manual",
        "store_visibility": "private",
        "price_confirmed": False,
    }
    assert migrated_submission(canonical_meta) == (canonical_meta, [], [])
    provided_proof_meta = dict(
        canonical_meta,
        license_proof={"status": "user-confirmed", "reference": "refs/license.pdf"},
    )
    assert migrated_submission(provided_proof_meta) == (provided_proof_meta, [], [])
    _, _, errors = migrated_submission(
        {"sales_start": "manual", "private": False, "price_confirmed": 1}
    )
    assert errors
    _, _, errors = migrated_submission(
        {"private": True, "store_visibility": "public", "sales_start": "manual"}
    )
    assert errors
    _, _, errors = migrated_submission(
        {"private": False, "sales_start": "automatic"}
    )
    assert errors
    _, _, errors = migrated_submission(
        {"schema_version": "9" * 1000, "sales_start": "manual", "store_visibility": "public"}
    )
    assert errors
    _, _, errors = migrated_submission(
        {"private": False, "store_visibility": [], "sales_start": "manual"}
    )
    assert errors

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "projects").mkdir()
        sink = StringIO()
        assert valid_slug("intake")
        assert not valid_slug("con")
        assert not valid_slug("active")
        assert not valid_slug("demo\n")
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_new(Namespace(root=str(root), slug="con")) == 1
            assert cmd_new(Namespace(root=str(root), slug="demo\n")) == 1
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_new(Namespace(root=str(root), slug="intake")) == 0
        session_path = root / "projects" / "intake" / "SESSION.md"
        initial_session = parse_session_for_migration(session_path.read_text(encoding="utf-8"))[0]
        assert initial_session["gate"] == "P0"
        assert initial_session["materials"] == "pending"

        base_intake = {
            "root": str(root),
            "materials": "received",
            "source": "photo",
            "count": 16,
            "text": "yes",
            "text_mode": "font",
            "character_name": "Hatch",
            "sample_candidates": 1,
            "publish": "yes",
        }
        _, intake_errors = p0_updates(Namespace(**dict(base_intake, publish="local-only")))
        assert not intake_errors
        character_intake = dict(base_intake, source="character")
        _, intake_errors = p0_updates(Namespace(**character_intake))
        assert not intake_errors
        _, intake_errors = p0_updates(
            Namespace(**dict(character_intake, character_name="pending"))
        )
        assert intake_errors
        before_rejection = session_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_p0(Namespace(**base_intake)) == 1
        assert session_path.read_bytes() == before_rejection

        source_material = root / "projects" / "intake" / "refs" / "source.jpg"
        source_material.write_bytes(b"")
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_p0(Namespace(**base_intake)) == 1
        assert session_path.read_bytes() == before_rejection
        Image.new("RGB", (80, 80), (90, 110, 130)).save(
            source_material, format="JPEG"
        )
        session_with_deprecated_field = session_path.read_text(encoding="utf-8").replace(
            "- publish: unknown\n", "- publish: unknown\n- consent: yes\n"
        )
        session_path.write_text(session_with_deprecated_field, encoding="utf-8")
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_p0(Namespace(**base_intake)) == 1
        session_path.write_bytes(before_rejection)
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_p0(Namespace(**base_intake)) == 0
        confirmed = parse_session_for_migration(session_path.read_text(encoding="utf-8"))[0]
        assert confirmed["gate"] == "P1"
        assert confirmed["character"] == "Hatch"
        assert not any(key in confirmed for key in ("adult", "consent", "rights"))
        after_confirmation = session_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_p0(Namespace(**base_intake)) == 1
        assert session_path.read_bytes() == after_confirmation

        project = session_path.parent
        save_png(
            Image.new("RGBA", (80, 80), (30, 80, 120, 255)),
            project / "refs" / "design-v01.png",
        )
        design_args = Namespace(
            root=str(root),
            image="refs/design-v01.png",
            reference=["refs/source.jpg"],
            hairstyle="short black hair",
            head_ratio=2.2,
            clothing="blue jacket",
            color=["#1A2B3C", "#F4D7C5"],
            eyes="round black eyes",
            accessories="none",
        )
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_design(design_args) == 0
        design_values = parse_session_for_migration(
            session_path.read_text(encoding="utf-8")
        )[0]
        assert design_values["gate"] == "P2" and design_values["design_version"] == "1"
        save_png(
            Image.new("RGBA", (120, 80), (40, 90, 130, 255)),
            project / "refs" / "three-view-v01.png",
        )
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_three_view(
                Namespace(root=str(root), image="refs/three-view-v01.png")
            ) == 0
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_record_learning(
                Namespace(
                    root=str(root), gate="P3", kind="lesson", summary="fixture",
                    impact="none", cause="test", resolution="recorded", candidate="reuse",
                )
            ) == 0
        assert "[lesson] fixture" in (project / "LEARNINGS.md").read_text(encoding="utf-8")

        session_path.write_text(
            update_session_text(
                session_path.read_text(encoding="utf-8"),
                {"gate": "P8", "validation": "ok", "submission": "drafted"},
            ),
            encoding="utf-8",
        )
        account_args = Namespace(
            root=str(root), account_name="Creator", seller_id="seller-1",
            registration_target="new-static-sticker",
        )
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_confirm_account(account_args) == 0
        wrong_completion = Namespace(
            root=str(root), account_name="Other", seller_id="seller-1",
            registration_target="new-static-sticker", preview_confirmed=True,
        )
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_complete_production(wrong_completion) == 1
        completion = Namespace(
            root=str(root), account_name="Creator", seller_id="seller-1",
            registration_target="new-static-sticker", preview_confirmed=True,
        )
        completion_output = StringIO()
        with redirect_stdout(completion_output), redirect_stderr(completion_output):
            assert cmd_complete_production(completion) == 0
        assert "制作が完了しました。問題なければ審査リクエストを実施してください。" in completion_output.getvalue()

        try:
            project_directory(str(root), "../escape")
        except ProjectPathError:
            pass
        else:
            raise AssertionError("project path traversal was accepted")

    with TemporaryDirectory() as directory:
        root = Path(directory)
        projects = root / "projects"
        projects.mkdir()
        original_writer = project_module.atomic_write_text

        def fail_active_write(path: Path, content: str) -> None:
            raise OSError("simulated ACTIVE write failure")

        project_module.atomic_write_text = fail_active_write
        try:
            sink = StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                assert cmd_new(Namespace(root=str(root), slug="rollback-new")) == 1
        finally:
            project_module.atomic_write_text = original_writer
        assert not (projects / "rollback-new").exists()
        assert not list(projects.glob(".rollback-new.new-*"))

        broken = projects / "broken"
        broken.mkdir()
        (broken / "SESSION.md").write_bytes(b"\xff\xfe")
        (projects / "ACTIVE").write_text("rollback-new\n", encoding="utf-8")
        before_active = (projects / "ACTIVE").read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_use(Namespace(root=str(root), slug="broken")) == 1
        assert (projects / "ACTIVE").read_bytes() == before_active

    with TemporaryDirectory() as directory:
        harness = Path(directory)
        project = harness / "projects" / "demo"
        for name in (
            "raw",
            "characters",
            "stamps",
            "character-layers",
            "text-layers",
            "review",
            "meta",
            "submit",
        ):
            (project / name).mkdir(parents=True, exist_ok=True)
        (harness / "projects" / "ACTIVE").write_text("demo\n", encoding="utf-8")
        (project / "SESSION.md").write_text(
            "# SESSION\n\n"
            "- schema_version: 4\n"
            "- project: demo\n"
            "- materials: received\n"
            "- count: 8\n"
            "- text: yes\n"
            "- text_mode: ai\n"
            "- text_check: not-run\n"
            "- text_mask_version: 0\n"
            "- review_version: 0\n"
            "- gate: P5\n",
            encoding="utf-8",
        )
        write_design_evidence_fixture(project)
        outdir, character_dir, text_dir = checked_output_directories(
            project,
            str(project / "stamps"),
            str(project / "character-layers"),
            str(project / "text-layers"),
            "font",
        )
        assert outdir == (project / "stamps").resolve()
        assert character_dir == (project / "character-layers").resolve()
        assert text_dir == (project / "text-layers").resolve()
        try:
            checked_output_directories(
                project,
                str(project / "stamps"),
                str(project / "stamps"),
                str(project / "text-layers"),
                "font",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("compose accepted overlapping output directories")
        assert checked_items([{"id": 1, "character": "characters/stamp01.png", "text": []}])
        try:
            checked_items(
                [
                    {"id": 1, "character": "characters/stamp01.png", "text": []},
                    {"id": 1, "character": "characters/stamp01.png", "text": []},
                ]
            )
        except ValueError:
            pass
        else:
            raise AssertionError("compose accepted duplicate manifest item IDs")

        review_input, review_output = checked_review_paths(
            str(project / "stamps"), str(project / "review" / "review-v01.png")
        )
        assert review_input == (project / "stamps").resolve()
        assert review_output == (project / "review" / "review-v01.png").resolve()
        assert expected_review_inputs(project) == [
            f"stamp{index:02d}.png" for index in range(1, 9)
        ]
        for name in expected_review_inputs(project):
            (project / "stamps" / name).write_bytes(b"fixture")
        assert len(checked_stamp_files(project / "stamps", expected_review_inputs(project))) == 8
        (project / "stamps" / "stamp-draft.png").write_bytes(b"draft")
        try:
            checked_stamp_files(project / "stamps", expected_review_inputs(project))
        except ValueError:
            pass
        else:
            raise AssertionError("review sheet accepted a non-canonical stamp-like draft")
        (project / "stamps" / "stamp-draft.png").unlink()
        (project / "review" / "review-v01.png").write_bytes(b"fixture")
        _, review_v02 = checked_review_paths(
            str(project / "stamps"), str(project / "review" / "review-v02.png")
        )
        assert review_v02.name == "review-v02.png"
        try:
            checked_review_paths(
                str(project / "stamps"), str(project / "review" / "review-v00.png")
            )
        except ValueError:
            pass
        else:
            raise AssertionError("review sheet accepted review-v00.png")

        verification_values, verification_errors = verification_session(project)
        assert not verification_errors and verification_values["count"] == "8"
        assert load_static_session(project, {"P5"})["text_mode"] == "ai"
        p5_session_source = (project / "SESSION.md").read_text(encoding="utf-8")
        (project / "SESSION.md").write_text(
            p5_session_source + "- rights: own\n", encoding="utf-8"
        )
        try:
            load_static_session(project, {"P5"})
        except ValueError:
            pass
        else:
            raise AssertionError("artifact command accepted deprecated SESSION fields")
        (project / "SESSION.md").write_text(p5_session_source, encoding="utf-8")
        (project / "SESSION.md").write_text(
            p5_session_source.replace("- materials: received", "- materials: pending"),
            encoding="utf-8",
        )
        try:
            load_static_session(project, {"P5"})
        except ValueError:
            pass
        else:
            raise AssertionError("artifact command accepted materials=pending after P0")
        try:
            expected_review_inputs(project)
        except ValueError:
            pass
        else:
            raise AssertionError("contact sheet accepted materials=pending after P0")
        _, pending_verification_errors = verification_session(project)
        assert pending_verification_errors
        (project / "SESSION.md").write_text(p5_session_source, encoding="utf-8")
        (project / "SESSION.md").write_text(
            p5_session_source.replace("- gate: P5", "- gate: P6"), encoding="utf-8"
        )
        try:
            load_static_session(project, {"P6"})
        except ValueError:
            pass
        else:
            raise AssertionError("P6 AI session accepted text_check=not-run")
        (project / "SESSION.md").write_text(p5_session_source, encoding="utf-8")
        assert verification_scope(verification_values, set(range(1, 9)), None) == set(
            range(1, 9)
        )
        for manifest_ids, requested_ids in (
            ({1}, None),
            (set(range(1, 9)), {1}),
        ):
            try:
                verification_scope(verification_values, manifest_ids, requested_ids)
            except ValueError:
                pass
            else:
                raise AssertionError("P5 verification accepted incomplete or partial evidence")
        sample_session = dict(verification_values, gate="P4")
        assert verification_scope(sample_session, {1}, {1}) == {1}
        try:
            verification_scope(sample_session, {1}, None)
        except ValueError:
            pass
        else:
            raise AssertionError("P4 verification accepted a check without --only 1")
        (project / "review" / "text-check-v02.json").write_text("{}\n", encoding="utf-8")
        assert next_version(project / "review") == 3
        manifest_path = project / "manifest.json"
        manifest_path.write_text('{"items": "P5 evidence fixture"}\n', encoding="utf-8")
        vision_path = project / "review" / "visual-reading.json"
        vision_fixture = {
            "schema_version": 1,
            "method": "ai-visual",
            "manifest_sha256": sha256_file(manifest_path),
            "items": [
                {
                    "id": index,
                    "file": f"stamp{index:02d}.png",
                    "sha256": sha256_file(project / "stamps" / f"stamp{index:02d}.png"),
                    "expected": f"line {index}",
                    "recognized": f"line {index}",
                    "status": "match",
                }
                for index in range(1, 9)
            ],
        }
        vision_path.write_text(
            json.dumps(vision_fixture, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        visual_rows = load_visual_review(
            str(vision_path), project, sha256_file(manifest_path), set(range(1, 9))
        )
        assert len(visual_rows) == 8 and visual_rows[1]["status"] == "match"
        evidence_rows = [
            {
                "id": index,
                "file": f"stamp{index:02d}.png",
                "sha256": sha256_file(project / "stamps" / f"stamp{index:02d}.png"),
                "expected": f"line {index}",
                "automatic_text": f"line {index}",
                "automatic_provider": "fixture-vision",
                "status": "match",
                "similarity": 1.0,
                "text_region": [0, 0, 8, 8],
                "mask_file": f"text-masks/v03/stamp{index:02d}.png",
                "mask_sha256": "pending",
            }
            for index in range(1, 9)
        ]
        mask_dir = project / "text-masks" / "v03"
        mask_dir.mkdir(parents=True)
        for row in evidence_rows:
            mask_path = project / row["mask_file"]
            Image.new("L", (8, 8), 255).save(mask_path, format="PNG")
            row["mask_sha256"] = sha256_file(mask_path)
        evidence = {
            "schema_version": 2,
            "version": 3,
            "project": "demo",
            "gate": "P5",
            "scope": "all",
            "session_count": 8,
            "manifest_sha256": sha256_file(manifest_path),
            "automatic_available": True,
            "automatic_method": "ocr",
            "automatic_provider": "fixture-vision",
            "automatic_model": "fixture-v1",
            "reason": "fixture",
            "rows": evidence_rows,
        }
        (project / "review" / "text-check-v03.json").write_text(
            json.dumps(evidence, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (project / "review" / "text-check-v03.md").write_text(
            "# complete P5 fixture\n", encoding="utf-8"
        )
        require_complete_text_evidence(project, 8, 3)
        # Schema 2 vision reports remain readable, without running their old provider.
        legacy_source = project / "review" / "legacy-vision.json"
        legacy_source.write_text("{\"legacy\": true}\n", encoding="utf-8")
        legacy_vision = dict(
            evidence, automatic_method="vision",
            vision_evidence_file="review/legacy-vision.json",
            vision_evidence_sha256=sha256_file(legacy_source),
        )
        legacy_report = project / "review" / "text-check-v03.json"
        legacy_report.write_text(json.dumps(legacy_vision), encoding="utf-8")
        require_complete_text_evidence(project, 8, 3)
        legacy_source.write_text("{\"legacy\": false}\n", encoding="utf-8")
        try:
            require_complete_text_evidence(project, 8, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("legacy vision evidence accepted a changed source")
        legacy_report.write_text(json.dumps(evidence), encoding="utf-8")
        write_review_evidence_fixture(project, 8)
        require_review_evidence(project, 8, 1)
        malformed_evidence = dict(evidence)
        malformed_evidence["rows"] = [dict(row) for row in evidence_rows]
        malformed_evidence["rows"][0]["status"] = []
        (project / "review" / "text-check-v03.json").write_text(
            json.dumps(malformed_evidence, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        try:
            require_complete_text_evidence(project, 8, 3)
        except ValueError:
            pass
        else:
            raise AssertionError("P5 evidence accepted a non-string row status")
        (project / "review" / "text-check-v03.json").write_text(
            json.dumps(evidence, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        p6_approved_source = p5_session_source.replace(
            "- text_check: not-run", "- text_check: ok"
        ).replace("- text_mask_version: 0", "- text_mask_version: 3").replace(
            "- review_version: 0", "- review_version: 1"
        ).replace(
            "- gate: P5", "- gate: P6"
        )
        (project / "SESSION.md").write_text(p6_approved_source, encoding="utf-8")
        assert load_static_session(project, {"P6"})["text_check"] == "ok"
        original_stamp = (project / "stamps" / "stamp01.png").read_bytes()
        (project / "stamps" / "stamp01.png").write_bytes(b"tampered")
        try:
            load_static_session(project, {"P6"})
        except ValueError:
            pass
        else:
            raise AssertionError("P6 accepted AI text evidence after a stamp changed")
        (project / "stamps" / "stamp01.png").write_bytes(original_stamp)
        (project / "SESSION.md").write_text(p5_session_source, encoding="utf-8")

        uppercase_source = project / "raw" / "stamp01.PNG"
        uppercase_source.write_bytes(b"fixture")
        try:
            checked_preprocess_paths(
                str(uppercase_source), str(project / "characters" / "stamp01.PNG")
            )
        except ValueError:
            pass
        else:
            raise AssertionError("preprocess accepted a non-canonical uppercase PNG filename")
        other_project = harness / "projects" / "other"
        (other_project / "review").mkdir(parents=True)
        try:
            checked_review_paths(
                str(project / "stamps"), str(other_project / "review" / "review-v01.png")
            )
        except ValueError:
            pass
        else:
            raise AssertionError("review sheet accepted a different project's output directory")

        previous_facade_project = os.environ.get(FACADE_PROJECT_ENV)
        os.environ[FACADE_PROJECT_ENV] = str(project.resolve())
        try:
            assert enforce_facade_project(project, "test") == project.resolve()
            try:
                enforce_facade_project(other_project, "test")
            except ValueError:
                pass
            else:
                raise AssertionError("facade project binding accepted another harness project")
        finally:
            if previous_facade_project is None:
                os.environ.pop(FACADE_PROJECT_ENV, None)
            else:
                os.environ[FACADE_PROJECT_ENV] = previous_facade_project

        session_path = project / "SESSION.md"
        submission_path = project / "meta" / "submission.json"
        zip_path = project / "submit" / "line-stamp-submit.zip"
        session_path.write_text("- project: demo\n", encoding="utf-8")
        submission_path.write_text("{}\n", encoding="utf-8")
        zip_path.write_bytes(b"fixture")
        layout_errors: list[str] = []
        assert check_project_layout(session_path, submission_path, zip_path, layout_errors) == project
        assert not layout_errors
        foreign_submission = other_project / "meta" / "submission.json"
        foreign_submission.parent.mkdir()
        foreign_layout_errors: list[str] = []
        check_project_layout(session_path, foreign_submission, zip_path, foreign_layout_errors)
        assert foreign_layout_errors

    with TemporaryDirectory() as directory:
        target = Path(directory) / "state.txt"
        target.write_text("old\n", encoding="utf-8")
        atomic_write_text(target, "new\n")
        assert target.read_text(encoding="utf-8") == "new\n"

        lock_path = Path(directory) / "operation.lock"
        with transaction_utils.exclusive_lock(lock_path, "first"):
            try:
                with transaction_utils.exclusive_lock(lock_path, "second"):
                    raise AssertionError("unreachable nested lock body")
            except transaction_utils.LockUnavailableError:
                pass
            else:
                raise AssertionError("cooperative lock allowed a second owner")
        assert lock_path.is_file()

    with TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "projects" / "legacy"
        (project / "meta").mkdir(parents=True)
        (root / "projects" / "ACTIVE").write_text("legacy\n", encoding="utf-8")
        session_path = project / "SESSION.md"
        session_path.write_text(old_session, encoding="utf-8")
        submission_path = project / "meta" / "submission.json"
        submission_path.write_text(json.dumps({"private": False}) + "\n", encoding="utf-8")
        mismatched_session = session_path.read_bytes()
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert session_path.read_bytes() == mismatched_session
        session_path.write_text(old_session.replace("- project: sample", "- project: legacy"), encoding="utf-8")
        no_material_session = session_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert session_path.read_bytes() == no_material_session
        (project / "refs").mkdir()
        (project / "refs" / "source.png").write_bytes(b"legacy source fixture")

        submission_path.write_bytes(b"\xff\xfe")
        invalid_utf8_submission = submission_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert submission_path.read_bytes() == invalid_utf8_submission

        submission_path.write_text('{"private": false, "value": NaN}\n', encoding="utf-8")
        non_finite_submission = submission_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert submission_path.read_bytes() == non_finite_submission

        submission_path.write_text('{"private": false, "private": true}\n', encoding="utf-8")
        duplicate_submission = submission_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert submission_path.read_bytes() == duplicate_submission
        submission_path.write_text(json.dumps({"private": False}) + "\n", encoding="utf-8")
        original_session = session_path.read_bytes()
        original_submission = submission_path.read_bytes()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 0
        assert session_path.read_bytes() == original_session
        assert submission_path.read_bytes() == original_submission
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=True)) == 0
        migrated_values = parse_session_for_migration(session_path.read_text(encoding="utf-8"))[0]
        assert migrated_values["schema_version"] == "4"
        assert migrated_values["materials"] == "received"
        assert not any(key in migrated_values for key in ("adult", "consent", "rights"))
        written_meta = json.loads(submission_path.read_text(encoding="utf-8"))
        assert written_meta["schema_version"] == 3 and written_meta["sales_start"] == "manual"
        assert (project / "LEARNINGS.md").read_text(encoding="utf-8").startswith(
            "# Project learnings\n"
        )
        assert list(project.glob("SESSION.md.pre-v4-*.bak"))
        assert list((project / "meta").glob("submission.json.pre-v4-*.bak"))
        backups_after_first_apply = list(project.rglob("*.bak"))
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=True)) == 0
        assert list(project.rglob("*.bak")) == backups_after_first_apply

    with TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "projects" / "invalid-session"
        project.mkdir(parents=True)
        (root / "projects" / "ACTIVE").write_text("invalid-session\n", encoding="utf-8")
        session_path = project / "SESSION.md"
        session_path.write_bytes(b"\xff\xfe")
        original_invalid_session = session_path.read_bytes()
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            assert cmd_migrate(Namespace(root=str(root), apply=False)) == 1
        assert session_path.read_bytes() == original_invalid_session

    with TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "projects" / "rollback"
        (project / "meta").mkdir(parents=True)
        (project / "refs").mkdir()
        (project / "refs" / "source.png").write_bytes(b"rollback source fixture")
        (root / "projects" / "ACTIVE").write_text("rollback\n", encoding="utf-8")
        session_path = project / "SESSION.md"
        session_path.write_text(
            old_session.replace("- project: sample", "- project: rollback"), encoding="utf-8"
        )
        submission_path = project / "meta" / "submission.json"
        submission_path.write_text(json.dumps({"private": False}) + "\n", encoding="utf-8")
        original_session = session_path.read_bytes()
        original_submission = submission_path.read_bytes()
        original_writer = project_module.atomic_write_text
        write_count = 0

        def fail_second_write(path: Path, content: str) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise OSError("simulated second-file failure")
            original_writer(path, content)

        project_module.atomic_write_text = fail_second_write
        try:
            sink = StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                assert cmd_migrate(Namespace(root=str(root), apply=True)) == 1
        finally:
            project_module.atomic_write_text = original_writer
        assert session_path.read_bytes() == original_session
        assert submission_path.read_bytes() == original_submission

    with TemporaryDirectory() as directory:
        root = Path(directory)
        valid_path = root / "valid.png"
        valid = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        ImageDraw.Draw(valid).rectangle((8, 8, 71, 71), fill=(20, 80, 40, 255))
        save_png(valid, valid_path)
        errors: list[str] = []
        warnings: list[str] = []
        validate_png(valid_path, None, (80, 80), (370, 320), 8, errors, warnings)
        assert not errors

        margin_11 = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        ImageDraw.Draw(margin_11).rectangle((11, 11, 68, 68), fill=(20, 80, 40, 255))
        margin_11_path = root / "margin-11.png"
        save_png(margin_11, margin_11_path)
        margin_11_errors: list[str] = []
        validate_png(margin_11_path, None, (80, 80), (370, 320), 12, margin_11_errors, [])
        assert any("below required 12px" in message for message in margin_11_errors)

        margin_12 = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
        ImageDraw.Draw(margin_12).rectangle((12, 12, 67, 67), fill=(20, 80, 40, 255))
        margin_12_path = root / "margin-12.png"
        save_png(margin_12, margin_12_path)
        margin_12_errors: list[str] = []
        margin_12_warnings: list[str] = []
        validate_png(
            margin_12_path, None, (80, 80), (370, 320), 12,
            margin_12_errors, margin_12_warnings,
        )
        assert not margin_12_errors and margin_12_warnings
        adjusted, was_adjusted = enforce_safe_margin(valid, required=12, target=16)
        assert was_adjusted and adjusted.size == valid.size

        no_dpi_path = root / "no-dpi.png"
        valid.save(no_dpi_path, format="PNG")
        no_dpi_errors: list[str] = []
        validate_png(no_dpi_path, None, (80, 80), (370, 320), 0, no_dpi_errors, [])
        assert any("72dpi" in message for message in no_dpi_errors)

        wrong_mode_path = root / "wrong-mode.png"
        Image.new("L", (80, 80), 0).save(wrong_mode_path, format="PNG", dpi=(72, 72))
        wrong_mode_errors: list[str] = []
        validate_png(wrong_mode_path, None, (80, 80), (370, 320), 0, wrong_mode_errors, [])
        assert any("mode is L" in message for message in wrong_mode_errors)

        undersized_path = root / "undersized.png"
        save_png(valid.resize((78, 80)), undersized_path)
        undersized_errors: list[str] = []
        validate_png(
            undersized_path, None, (80, 80), (370, 320), 0, undersized_errors, []
        )
        assert any("below (80, 80)" in message for message in undersized_errors)

        oversized_path = root / "oversized.png"
        save_png(valid.resize((372, 320)), oversized_path)
        oversized_errors: list[str] = []
        validate_png(
            oversized_path, None, (80, 80), (370, 320), 0, oversized_errors, []
        )
        assert any("exceeds (370, 320)" in message for message in oversized_errors)

        odd_path = root / "odd.png"
        save_png(valid.resize((81, 80)), odd_path)
        odd_errors: list[str] = []
        validate_png(odd_path, None, (80, 80), (370, 320), 0, odd_errors, [])
        assert any("odd dimensions" in message for message in odd_errors)

        exact_errors: list[str] = []
        validate_png(valid_path, (240, 240), None, None, 0, exact_errors, [])
        assert any("!= (240, 240)" in message for message in exact_errors)

        too_large_path = root / "too-large.png"
        too_large_path.write_bytes(b"x" * 1_000_001)
        too_large_errors: list[str] = []
        validate_png(
            too_large_path, None, (80, 80), (370, 320), 0, too_large_errors, []
        )
        assert any("exceeds 1MB" in message for message in too_large_errors)

        opaque_rgb_path = root / "opaque-rgb.png"
        Image.new("RGB", (80, 80), (255, 255, 255)).save(
            opaque_rgb_path, format="PNG", dpi=(72, 72)
        )
        opaque_errors: list[str] = []
        validate_png(opaque_rgb_path, None, (80, 80), (370, 320), 0, opaque_errors, [])
        assert any("no fully transparent background" in message for message in opaque_errors)

        pinhole_path = root / "pinhole.png"
        pinhole = Image.new("RGBA", (80, 80), (20, 80, 40, 255))
        pinhole.putpixel((40, 40), (0, 0, 0, 0))
        save_png(pinhole, pinhole_path)
        pinhole_errors: list[str] = []
        validate_png(pinhole_path, None, (80, 80), (370, 320), 0, pinhole_errors, [])
        assert any("exterior transparent background" in message for message in pinhole_errors)

        corner_only_path = root / "corner-only.png"
        corner_only = Image.new("RGBA", (80, 80), (20, 80, 40, 255))
        corner_only.putpixel((0, 0), (0, 0, 0, 0))
        save_png(corner_only, corner_only_path)
        corner_only_errors: list[str] = []
        validate_png(
            corner_only_path, None, (80, 80), (370, 320), 0, corner_only_errors, []
        )
        assert any("exterior transparent background" in message for message in corner_only_errors)

        ring_path = root / "transparent-ring.png"
        ring = Image.new("RGBA", (80, 80), (20, 80, 40, 255))
        ring_pixels = ring.load()
        for x in range(80):
            ring_pixels[x, 0] = (0, 0, 0, 0)
            ring_pixels[x, 79] = (0, 0, 0, 0)
        for y in range(80):
            ring_pixels[0, y] = (0, 0, 0, 0)
            ring_pixels[79, y] = (0, 0, 0, 0)
        save_png(ring, ring_path)
        ring_errors: list[str] = []
        validate_png(ring_path, None, (80, 80), (370, 320), 0, ring_errors, [])
        assert any("exterior transparent background" in message for message in ring_errors)

        blank_path = root / "blank.png"
        save_png(Image.new("RGBA", (80, 80), (0, 0, 0, 0)), blank_path)
        blank_errors: list[str] = []
        validate_png(blank_path, None, (80, 80), (370, 320), 0, blank_errors, [])
        assert any("no visible content" in message for message in blank_errors)

        transparent_rgb_path = root / "transparent-rgb.png"
        transparent_rgb = Image.new("RGB", (80, 80), (0, 0, 0))
        ImageDraw.Draw(transparent_rgb).rectangle((8, 8, 71, 71), fill=(20, 80, 40))
        transparent_rgb.save(
            transparent_rgb_path,
            format="PNG",
            dpi=(72, 72),
            transparency=(0, 0, 0),
        )
        transparent_rgb_errors: list[str] = []
        validate_png(
            transparent_rgb_path,
            None,
            (80, 80),
            (370, 320),
            0,
            transparent_rgb_errors,
            [],
        )
        assert not transparent_rgb_errors

        disguised_jpeg_path = root / "disguised.png"
        Image.new("RGB", (80, 80), (255, 255, 255)).save(
            disguised_jpeg_path, format="JPEG", dpi=(72, 72)
        )
        disguised_errors: list[str] = []
        validate_png(
            disguised_jpeg_path, None, (80, 80), (370, 320), 0, disguised_errors, []
        )
        assert any("format is JPEG" in message for message in disguised_errors)

        animated_path = root / "animated.png"
        frame_one = valid.copy()
        frame_two = valid.copy()
        ImageDraw.Draw(frame_two).rectangle((20, 20, 59, 59), fill=(180, 40, 40, 255))
        frame_one.save(
            animated_path,
            format="PNG",
            save_all=True,
            append_images=[frame_two],
            duration=100,
            loop=0,
            dpi=(72, 72),
        )
        animated_errors: list[str] = []
        validate_png(animated_path, None, (80, 80), (370, 320), 0, animated_errors, [])
        assert any("multi-frame" in message for message in animated_errors)

        bad_zip = root / "bad.zip"
        bad_zip.write_bytes(b"not a ZIP")
        bad_zip_errors: list[str] = []
        validate_zip(bad_zip, root, ["valid.png"], bad_zip_errors)
        assert any("ZIP is not readable" in message for message in bad_zip_errors)

        missing_local_zip = root / "missing-local.zip"
        with zipfile.ZipFile(missing_local_zip, "w") as archive:
            archive.writestr("missing.png", b"data")
        missing_local_errors: list[str] = []
        validate_zip(missing_local_zip, root, ["missing.png"], missing_local_errors)
        assert any("local file is missing" in message for message in missing_local_errors)

        symlink_member_zip = root / "symlink-member.zip"
        symlink_info = zipfile.ZipInfo("valid.png")
        symlink_info.create_system = 3
        symlink_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(symlink_member_zip, "w") as archive:
            archive.writestr(symlink_info, valid_path.read_bytes())
        symlink_member_errors: list[str] = []
        validate_zip(symlink_member_zip, root, ["valid.png"], symlink_member_errors)
        assert any("not a regular file" in message for message in symlink_member_errors)

        dos_directory_zip = root / "dos-directory-member.zip"
        dos_directory_info = zipfile.ZipInfo("valid.png")
        dos_directory_info.external_attr = 0x10
        with zipfile.ZipFile(dos_directory_zip, "w") as archive:
            archive.writestr(dos_directory_info, valid_path.read_bytes())
        dos_directory_errors: list[str] = []
        validate_zip(dos_directory_zip, root, ["valid.png"], dos_directory_errors)
        assert any("is a directory" in message for message in dos_directory_errors)

        corrupt_zip = root / "corrupt-member.zip"
        with zipfile.ZipFile(corrupt_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("valid.png", valid_path.read_bytes())
        with zipfile.ZipFile(corrupt_zip) as archive:
            info = archive.getinfo("valid.png")
        corrupt_bytes = bytearray(corrupt_zip.read_bytes())
        filename_length = int.from_bytes(
            corrupt_bytes[info.header_offset + 26 : info.header_offset + 28], "little"
        )
        extra_length = int.from_bytes(
            corrupt_bytes[info.header_offset + 28 : info.header_offset + 30], "little"
        )
        payload_offset = info.header_offset + 30 + filename_length + extra_length
        corrupt_bytes[payload_offset] ^= 0xFF
        corrupt_zip.write_bytes(corrupt_bytes)
        corrupt_errors: list[str] = []
        validate_zip(corrupt_zip, root, ["valid.png"], corrupt_errors)
        assert corrupt_errors, "corrupt ZIP member was accepted"

    for boundary_count in (8, 16, 24, 32, 40):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "projects" / f"pack-{boundary_count}"
            source_dir = project / "stamps"
            outdir = project / "submit"
            source_dir.mkdir(parents=True)
            outdir.mkdir()
            (project.parent / "ACTIVE").write_text(
                f"pack-{boundary_count}\n", encoding="utf-8"
            )
            (project / "SESSION.md").write_text(
                "# SESSION\n\n"
                "- schema_version: 4\n"
                f"- project: pack-{boundary_count}\n"
                "- materials: received\n"
                f"- count: {boundary_count}\n"
                "- text: yes\n"
                "- text_mode: font\n"
                "- text_check: n/a\n"
                "- text_mask_version: 0\n"
                "- review_version: 1\n"
                "- gate: P6\n",
                encoding="utf-8",
            )
            write_design_evidence_fixture(project)
            for index in range(1, boundary_count + 1):
                stamp = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
                ImageDraw.Draw(stamp).rectangle(
                    (10, 10, 89, 89), fill=(20 + index, 80, 40, 255)
                )
                save_png(stamp, source_dir / project_stamp_name(index))
            write_review_evidence_fixture(project, boundary_count)
            with redirect_stdout(StringIO()):
                zip_path = package_static(source_dir, outdir, boundary_count)
            expected_stamp_names = [
                submission_stamp_name(index)
                for index in range(1, boundary_count + 1)
            ]
            naming_errors: list[str] = []
            validate_submission_names(outdir, boundary_count, naming_errors, [])
            validate_stamp_sources(project, outdir, boundary_count, naming_errors)
            validate_zip(
                zip_path,
                outdir,
                ["main.png", "tab.png", *expected_stamp_names],
                naming_errors,
            )
            assert not naming_errors

    with TemporaryDirectory() as directory:
        root = Path(directory)
        project = root / "projects" / "pack"
        source_dir = project / "stamps"
        outdir = project / "submit"
        source_dir.mkdir(parents=True)
        outdir.mkdir()
        (project.parent / "ACTIVE").write_text("pack\n", encoding="utf-8")
        (project / "SESSION.md").write_text(
            "# SESSION\n\n"
            "- schema_version: 4\n"
            "- project: pack\n"
            "- materials: received\n"
            "- count: 8\n"
            "- text: yes\n"
            "- text_mode: font\n"
            "- text_check: n/a\n"
            "- text_mask_version: 0\n"
            "- review_version: 1\n"
            "- gate: P6\n",
            encoding="utf-8",
        )
        write_design_evidence_fixture(project)
        font_session = (project / "SESSION.md").read_text(encoding="utf-8")
        (project / "SESSION.md").write_text(
            font_session.replace("- text_mask_version: 0", "- text_mask_version: 2"),
            encoding="utf-8",
        )
        try:
            load_static_session(project, {"P6"})
        except ValueError as exc:
            assert "requires text_mask_version=0" in str(exc)
        else:
            raise AssertionError("font text mode accepted stale AI text masks")
        (project / "SESSION.md").write_text(font_session, encoding="utf-8")
        for index in range(1, 9):
            stamp = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            ImageDraw.Draw(stamp).rectangle(
                (10, 10, 89, 89), fill=(20 + index, 80, 40, 255)
            )
            save_png(stamp, source_dir / f"stamp{index:02d}.png")
        write_review_evidence_fixture(project, 8)

        unrelated_path = outdir / "stamp-draft.png"
        unrelated_path.write_bytes(b"keep this unrelated draft")
        other_zip = outdir / "archive.zip"
        other_zip.write_bytes(b"keep this unrelated archive")
        nested_note = outdir / "user-assets" / "notes.txt"
        nested_note.parent.mkdir()
        nested_note.write_text("keep this user directory", encoding="utf-8")
        legacy_path = outdir / "stamp01.png"
        legacy_path.write_bytes(b"preserve this legacy output")
        (outdir / "01.png").write_bytes(b"old managed output")
        sink = StringIO()
        with redirect_stdout(sink):
            zip_path = package_static(source_dir, outdir, 8)

        assert unrelated_path.read_bytes() == b"keep this unrelated draft"
        assert other_zip.read_bytes() == b"keep this unrelated archive"
        assert nested_note.read_text(encoding="utf-8") == "keep this user directory"
        assert legacy_path.read_bytes() == b"preserve this legacy output"
        assert "WARN preserved legacy submit files excluded from ZIP: stamp01.png" in sink.getvalue()
        assert not list(outdir.glob(".line-stamp-package-*"))
        expected_stamp_names = [submission_stamp_name(index) for index in range(1, 9)]
        submission_name_errors: list[str] = []
        legacy_warnings: list[str] = []
        assert validate_submission_names(
            outdir, 8, submission_name_errors, legacy_warnings
        ) == expected_stamp_names
        assert not submission_name_errors
        assert legacy_warnings and "stamp01.png" in legacy_warnings[0]

        missing_bytes = (outdir / "08.png").read_bytes()
        (outdir / "08.png").unlink()
        missing_name_errors: list[str] = []
        validate_submission_names(outdir, 8, missing_name_errors, [])
        assert any("stamp names differ" in message for message in missing_name_errors)
        (outdir / "08.png").write_bytes(missing_bytes)

        (outdir / "09.png").write_bytes(missing_bytes)
        extra_name_errors: list[str] = []
        validate_submission_names(outdir, 8, extra_name_errors, [])
        assert any("stamp names differ" in message for message in extra_name_errors)
        (outdir / "09.png").unlink()

        source_binding_errors: list[str] = []
        validate_stamp_sources(project, outdir, 8, source_binding_errors)
        assert not source_binding_errors
        tampered_submission = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(tampered_submission).ellipse(
            (10, 10, 89, 89), fill=(180, 30, 60, 255)
        )
        save_png(tampered_submission, outdir / "01.png")
        source_binding_errors = []
        validate_stamp_sources(project, outdir, 8, source_binding_errors)
        assert any("differs from reviewed" in message for message in source_binding_errors)
        (outdir / "01.png").write_bytes((source_dir / "stamp01.png").read_bytes())
        for index, name in enumerate(expected_stamp_names, start=1):
            assert (outdir / name).read_bytes() == (
                source_dir / project_stamp_name(index)
            ).read_bytes()

        pack_errors: list[str] = []
        pack_warnings: list[str] = []
        validate_png(outdir / "main.png", (240, 240), None, None, 0, pack_errors, pack_warnings)
        validate_png(outdir / "tab.png", (96, 74), None, None, 0, pack_errors, pack_warnings)
        for name in expected_stamp_names:
            validate_png(
                outdir / name,
                None,
                (80, 80),
                (370, 320),
                8,
                pack_errors,
                pack_warnings,
            )
        member_names = ["main.png", "tab.png", *expected_stamp_names]
        validate_zip(zip_path, outdir, member_names, pack_errors)
        assert not pack_errors

        prior_outputs = {name: (outdir / name).read_bytes() for name in [*member_names, zip_path.name]}
        review_v01_path = project / "review" / "review-v01.json"
        original_review_v01 = review_v01_path.read_bytes()
        changed = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(changed).ellipse((8, 8, 91, 91), fill=(180, 40, 40, 255))
        save_png(changed, source_dir / "stamp01.png")
        write_review_evidence_fixture(project, 8, version=2)
        session_path = project / "SESSION.md"
        session_path.write_text(
            update_session_text(
                session_path.read_text(encoding="utf-8"),
                {"review_version": "2"},
            ),
            encoding="utf-8",
        )
        assert review_v01_path.read_bytes() == original_review_v01
        original_replace = transaction_utils.replace_path
        replace_count = 0
        fail_at = len(prior_outputs) + 3

        def fail_during_install(source: Path, destination: Path) -> None:
            nonlocal replace_count
            replace_count += 1
            if replace_count == fail_at:
                raise OSError("simulated package install failure")
            original_replace(source, destination)

        transaction_utils.replace_path = fail_during_install
        try:
            try:
                with redirect_stdout(sink):
                    package_static(source_dir, outdir, 8)
            except OSError:
                pass
            else:
                raise AssertionError("simulated package failure did not occur")
        finally:
            transaction_utils.replace_path = original_replace
        assert replace_count == fail_at
        for name, old_bytes in prior_outputs.items():
            assert (outdir / name).read_bytes() == old_bytes
        assert legacy_path.read_bytes() == b"preserve this legacy output"
        assert not list(outdir.glob(".line-stamp-package-*"))
        assert (outdir / ".line-stamp-package.lock").is_file()

        tampered_zip = outdir / "tampered.zip"
        with zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in member_names:
                data = b"tampered" if name == "01.png" else (outdir / name).read_bytes()
                archive.writestr(name, data)
        tampered_errors: list[str] = []
        validate_zip(tampered_zip, outdir, member_names, tampered_errors)
        assert any("01.png differs" in message for message in tampered_errors)

        for wrong_name in ("stamp01.png", "01.PNG"):
            wrong_name_zip = outdir / f"wrong-{wrong_name.replace('.', '-')}.zip"
            with zipfile.ZipFile(
                wrong_name_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name in member_names:
                    archive_name = wrong_name if name == "01.png" else name
                    archive.writestr(archive_name, (outdir / name).read_bytes())
            wrong_name_errors: list[str] = []
            validate_zip(wrong_name_zip, outdir, member_names, wrong_name_errors)
            assert any("ZIP members differ" in message for message in wrong_name_errors)

        try:
            package_static(source_dir, outdir, 8, zip_name="../escape.zip")
        except ValueError:
            pass
        else:
            raise AssertionError("package_static accepted a ZIP path outside outdir")
        assert not (root / "escape.zip").exists()
        for unsafe_zip_name in ("payload:pack.zip", "CON.zip", "LPT1.backup.zip"):
            try:
                package_static(source_dir, outdir, 8, zip_name=unsafe_zip_name)
            except ValueError:
                pass
            else:
                raise AssertionError(f"package_static accepted unsafe ZIP name {unsafe_zip_name!r}")

        blocked_output = outdir / "blocked.zip"
        blocked_output.mkdir()
        try:
            package_static(source_dir, outdir, 8, zip_name="blocked.zip")
        except IsADirectoryError:
            pass
        else:
            raise AssertionError("package_static replaced a user directory")
        assert blocked_output.is_dir()
        for name, old_bytes in prior_outputs.items():
            assert (outdir / name).read_bytes() == old_bytes
        assert legacy_path.read_bytes() == b"preserve this legacy output"

    repo_root = Path(__file__).resolve().parents[4]
    facade = repo_root / "scripts" / "line_stamp.py"
    public_commands = {
        "project": "project.py",
        "preprocess-character": "preprocess_character.py",
        "compose-static": "compose_static.py",
        "verify-text": "verify_text.py",
        "make-contact-sheet": "make_contact_sheet.py",
        "package-static": "package_static.py",
        "validate-pack": "validate_pack.py",
        "check-publish-ready": "check_publish_ready.py",
        "self-test": "self_test.py",
    }
    narrow_stdio_environment = dict(os.environ)
    narrow_stdio_environment["PYTHONIOENCODING"] = "cp1252"
    for command, implementation in public_commands.items():
        result = subprocess.run(
            [sys.executable, str(facade), command, "--help"],
            cwd=repo_root,
            env=narrow_stdio_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, (command, result.returncode, result.stderr)
        output = result.stdout + result.stderr
        assert b".agents" not in output
        assert implementation.encode("ascii") not in output
    unknown = subprocess.run(
        [sys.executable, str(facade), "not-a-command"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert unknown.returncode == 2
    assert b".agents" not in unknown.stdout + unknown.stderr

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
    outlined_ring = add_white_outline(text_like_ring, 10)
    assert outlined_ring.size == (60, 60)
    assert outlined_ring.getpixel((29, 29))[3] == 0, "white outline filled a text counter"
    assert outlined_ring.getpixel((9, 30))[3] > 0, "white outline was not added outside the shape"
    assert text_region({"text_region": [8, 8, 32, 32]}, (40, 40), 1) == (8, 8, 32, 32)
    protected = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(protected).rectangle((14, 14, 25, 25), fill=255)
    unprotected = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(unprotected).rectangle((8, 8, 9, 9), fill=255)
    assert not internal_hole_sizes_outside_mask(text_like_ring, protected)
    assert internal_hole_sizes_outside_mask(text_like_ring, unprotected)
    empty_mask = Image.new("L", (40, 40), 0)
    try:
        internal_hole_sizes_outside_mask(text_like_ring, empty_mask)
    except ValueError as exc:
        assert "non-empty text-only region" in str(exc)
    else:
        raise AssertionError("micro-hole inspection accepted an empty text mask")

    antialiased = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
    antialiased.putpixel((1, 1), (20, 80, 40, 128))
    outlined_antialiased = add_white_outline(antialiased, 1)
    assert outlined_antialiased.getpixel((2, 2)) == (20, 80, 40, 128)

    dirty = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    dirty.putpixel((0, 0), (255, 255, 255, 5))
    clean = sanitize_alpha(dirty, alpha_floor=12)
    assert clean.getpixel((0, 0)) == (0, 0, 0, 0), "low-alpha RGB was not cleared"
    assert hidden_rgb_pixels(clean) == 0
    print(
        "PASS schema-migration counted-length layer-isolation alpha-cleanup "
        "micro-hole-policy pack-validation submission-naming safe-packaging "
        "p0-transition migration-rollback "
        "facade-contract"
    )
    check_visual_review_flow()
    print("PASS ai-visual-review p4-p5-recording stale-evidence-rejection legacy-text-compatibility")


if __name__ == "__main__":
    main()
