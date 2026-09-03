#!/usr/bin/env python3
"""Claude compatibility wrapper for the vendor-neutral PreToolUse policy."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
    hook = root / "scripts" / "hooks" / "pre_tool_use.mjs"
    try:
        result = subprocess.run(
            ["node", str(hook), "claude"],
            input=sys.stdin.buffer.read(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        print(f"[claude-hook-wrapper] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
