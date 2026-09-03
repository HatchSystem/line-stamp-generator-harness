"""Bind skill scripts to the project selected and locked by the public facade."""
from __future__ import annotations

import os
from pathlib import Path


FACADE_PROJECT_ENV = "LINE_STAMP_FACADE_PROJECT"


def enforce_facade_project(project: Path, operation: str) -> Path:
    """Reject paths outside the exact project selected by scripts/line_stamp.py.

    The environment variable is deliberately optional for import-level unit tests.
    The public facade always sets it for artifact commands, and AGENTS.md forbids
    direct invocation of these implementation scripts.
    """
    resolved = project.resolve()
    selected_value = os.environ.get(FACADE_PROJECT_ENV)
    if selected_value is None:
        return resolved
    selected = Path(selected_value)
    if not selected.is_absolute():
        raise ValueError(f"{FACADE_PROJECT_ENV} must be an absolute path")
    selected_resolved = selected.resolve()
    if resolved != selected_resolved:
        raise ValueError(
            f"{operation} project {resolved} differs from the public facade project "
            f"{selected_resolved}"
        )
    return resolved
