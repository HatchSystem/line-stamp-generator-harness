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
    fill_small_transparent_holes,
    hidden_rgb_pixels,
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
    cmd_migrate,
    cmd_new,
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
    require_complete_text_evidence,
    require_review_evidence,
    sha256_file,
)
from validate_pack import validate_png, validate_stamp_sources, validate_zip
from verify_text import next_version, verification_scope, verification_session
import transaction_utils


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


def main() -> None:
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
        "schema_version": "3",
        "project": "demo",
        "materials": "received",
        "source": "character",
        "count": "16",
        "text": "yes",
        "text_mode": "font",
        "text_check": "n/a",
        "gate": "P7",
        "character": "Hatch",
        "publish": "yes",
        "validation": "ok",
        "review_version": "1",
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
        assert updates["schema_version"] == "3"
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
        {"schema_version": "02", "publish": "yes", "materials": "received"}
    )
    assert not errors and updates["schema_version"] == "3"

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
    assert "- schema_version: 3" in migrated_session
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
        source_material.write_bytes(b"p0 fixture")
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
            "- schema_version: 3\n"
            "- project: demo\n"
            "- materials: received\n"
            "- count: 8\n"
            "- text: yes\n"
            "- text_mode: ai\n"
            "- text_check: not-run\n"
            "- review_version: 0\n"
            "- gate: P5\n",
            encoding="utf-8",
        )
        outdir, character_dir, text_dir = checked_output_directories(
            project,
            str(project / "stamps"),
            str(project / "character-layers"),
            str(project / "text-layers"),
            "font",
        )
        assert outdir == project / "stamps"
        assert character_dir == project / "character-layers"
        assert text_dir == project / "text-layers"
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
        assert review_input == project / "stamps"
        assert review_output == project / "review" / "review-v01.png"
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
        evidence_rows = [
            {
                "id": index,
                "file": f"stamp{index:02d}.png",
                "sha256": sha256_file(project / "stamps" / f"stamp{index:02d}.png"),
                "expected": f"line {index}",
                "ocr": "",
                "status": "visual-required",
                "similarity": None,
            }
            for index in range(1, 9)
        ]
        evidence = {
            "schema_version": 1,
            "version": 3,
            "project": "demo",
            "gate": "P5",
            "scope": "all",
            "session_count": 8,
            "manifest_sha256": sha256_file(manifest_path),
            "ocr_available": False,
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
        require_complete_text_evidence(project, 8)
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
            require_complete_text_evidence(project, 8)
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
        ).replace("- review_version: 0", "- review_version: 1").replace(
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
        assert migrated_values["schema_version"] == "3"
        assert migrated_values["materials"] == "received"
        assert not any(key in migrated_values for key in ("adult", "consent", "rights"))
        written_meta = json.loads(submission_path.read_text(encoding="utf-8"))
        assert written_meta["schema_version"] == 3 and written_meta["sales_start"] == "manual"
        assert list(project.glob("SESSION.md.pre-v3-*.bak"))
        assert list((project / "meta").glob("submission.json.pre-v3-*.bak"))
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
            "- schema_version: 3\n"
            "- project: pack\n"
            "- materials: received\n"
            "- count: 8\n"
            "- text: yes\n"
            "- text_mode: font\n"
            "- text_check: n/a\n"
            "- review_version: 1\n"
            "- gate: P6\n",
            encoding="utf-8",
        )
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
        (outdir / "stamp01.png").write_bytes(b"old managed output")
        sink = StringIO()
        with redirect_stdout(sink):
            zip_path = package_static(source_dir, outdir, 8)

        assert unrelated_path.read_bytes() == b"keep this unrelated draft"
        assert other_zip.read_bytes() == b"keep this unrelated archive"
        assert nested_note.read_text(encoding="utf-8") == "keep this user directory"
        assert not list(outdir.glob(".line-stamp-package-*"))
        expected_stamp_names = [f"stamp{index:02d}.png" for index in range(1, 9)]
        source_binding_errors: list[str] = []
        validate_stamp_sources(project, outdir, expected_stamp_names, source_binding_errors)
        assert not source_binding_errors
        tampered_submission = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(tampered_submission).ellipse(
            (10, 10, 89, 89), fill=(180, 30, 60, 255)
        )
        save_png(tampered_submission, outdir / "stamp01.png")
        source_binding_errors = []
        validate_stamp_sources(project, outdir, expected_stamp_names, source_binding_errors)
        assert any("differs from reviewed" in message for message in source_binding_errors)
        (outdir / "stamp01.png").write_bytes((source_dir / "stamp01.png").read_bytes())
        for name in expected_stamp_names:
            assert (outdir / name).read_bytes() == (source_dir / name).read_bytes()

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
        changed = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(changed).ellipse((8, 8, 91, 91), fill=(180, 40, 40, 255))
        save_png(changed, source_dir / "stamp01.png")
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
        for name, old_bytes in prior_outputs.items():
            assert (outdir / name).read_bytes() == old_bytes
        assert not list(outdir.glob(".line-stamp-package-*"))
        assert (outdir / ".line-stamp-package.lock").is_file()

        tampered_zip = outdir / "tampered.zip"
        with zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in member_names:
                data = b"tampered" if name == "stamp01.png" else (outdir / name).read_bytes()
                archive.writestr(name, data)
        tampered_errors: list[str] = []
        validate_zip(tampered_zip, outdir, member_names, tampered_errors)
        assert any("stamp01.png differs" in message for message in tampered_errors)

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
    for command, implementation in public_commands.items():
        result = subprocess.run(
            [sys.executable, str(facade), command, "--help"],
            cwd=repo_root,
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
        "micro-hole-policy pack-validation safe-packaging p0-transition migration-rollback "
        "facade-contract"
    )


if __name__ == "__main__":
    main()
