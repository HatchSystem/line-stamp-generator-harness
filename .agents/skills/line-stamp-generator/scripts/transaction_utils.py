"""Same-filesystem artifact installation with rollback and cooperative locking."""
from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class ArtifactRollbackError(RuntimeError):
    """Raised when originals could not be fully restored; staging is preserved."""


class LockUnavailableError(RuntimeError):
    """Raised when another cooperative operation already owns a lock."""


def replace_path(source: Path, destination: Path) -> None:
    """Replace one path; kept as a seam for failure-injection regression tests."""
    source.replace(destination)


@contextmanager
def exclusive_lock(path: Path, description: str) -> Iterator[None]:
    """Hold a nonblocking OS advisory lock that the kernel releases on process exit.

    The tiny lock file is intentionally persistent. Removing a lock pathname after
    unlocking introduces an unlink/open race; only the OS lock represents ownership.
    """
    if path.is_symlink():
        raise ValueError(f"lock path must not be a symlink: {path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    identity = os.fstat(handle.fileno())
    if not stat.S_ISREG(identity.st_mode):
        handle.close()
        raise ValueError(f"lock path must be a regular file: {path}")

    def verify_identity() -> None:
        if path.is_symlink():
            raise RuntimeError(f"lock path changed into a symlink: {path}")
        current = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or not os.path.samestat(identity, current):
            raise RuntimeError(f"lock path identity changed: {path}")

    acquired = False
    try:
        verify_identity()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise LockUnavailableError(
                f"another operation owns lock {path} ({description})"
            ) from exc
        acquired = True
        try:
            verify_identity()
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def install_files_transaction(
    staging_root: Path,
    installs: list[tuple[Path, Path]],
) -> None:
    """Install staged files and restore the complete prior set on any BaseException.

    Sources must live under ``staging_root``. Destinations may span sibling artifact
    directories but must share its filesystem; callers create and validate those
    directories first. If rollback itself fails, backups remain under staging_root.
    """
    staging_root = staging_root.resolve()
    if not installs:
        raise ValueError("artifact transaction has no files to install")

    resolved_destinations: set[Path] = set()
    normalized: list[tuple[Path, Path]] = []
    for source, destination in installs:
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"staged artifact is missing or a symlink: {source}")
        resolved_source = source.resolve()
        if not resolved_source.is_relative_to(staging_root):
            raise ValueError(f"staged artifact escapes staging root: {source}")
        if destination.parent.is_symlink() or not destination.parent.is_dir():
            raise ValueError(f"artifact destination parent is not a regular directory: {destination.parent}")
        if destination.is_symlink():
            raise ValueError(f"refusing to replace symlink output: {destination}")
        if os.path.lexists(destination) and not destination.is_file():
            raise IsADirectoryError(f"refusing to replace non-file output: {destination}")
        resolved_destination = destination.resolve()
        if resolved_destination in resolved_destinations:
            raise ValueError(f"duplicate artifact destination: {destination}")
        resolved_destinations.add(resolved_destination)
        normalized.append((resolved_source, destination))

    backup_dir = staging_root / "backups"
    backup_dir.mkdir()
    backed_up: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for index, (_, destination) in enumerate(normalized):
            if destination.is_file():
                backup = backup_dir / f"{index:04d}-{destination.name}"
                replace_path(destination, backup)
                backed_up.append((destination, backup))
        for source, destination in normalized:
            replace_path(source, destination)
            installed.append(destination)
    except BaseException as original_error:
        rollback_errors: list[str] = []
        for destination in reversed(installed):
            try:
                if destination.is_symlink():
                    raise OSError(f"installed destination changed into a symlink: {destination}")
                if destination.is_file():
                    destination.unlink()
                elif os.path.lexists(destination):
                    raise OSError(f"installed destination changed type: {destination}")
            except BaseException as exc:
                rollback_errors.append(f"remove new {destination}: {exc}")
        for destination, backup in reversed(backed_up):
            try:
                if os.path.lexists(destination):
                    raise OSError(f"destination unexpectedly exists: {destination}")
                if backup.is_symlink() or not backup.is_file():
                    raise OSError(f"backup is missing or changed type: {backup}")
                backup.replace(destination)
            except BaseException as exc:
                rollback_errors.append(f"restore old {destination}: {exc}")
        if rollback_errors:
            raise ArtifactRollbackError(
                "artifact install failed and rollback was incomplete; preserve staging at "
                f"{staging_root}: {'; '.join(rollback_errors)}"
            ) from original_error
        raise
