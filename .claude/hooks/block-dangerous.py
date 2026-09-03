#!/usr/bin/env python3
"""PreToolUse hook for Bash: deny destructive commands and photo leakage into submit ZIPs.

Reads the official hook JSON from stdin. Prints a JSON decision. Fails open on malformed input
(exit 0, no output) so the hook never breaks a session because of its own bug.
"""
from __future__ import annotations

import json
import re
import sys

DENY_PATTERNS = (
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b", "rm -rf は禁止。不要ファイルは tmp/ へ移動して報告する"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+.*\b(projects|submit)\b", "projects/ submit/ の再帰削除は禁止"),
    (r"\bgit\s+push\b.*(--force\b|-f\b|--force-with-lease\b)", "git push --force は禁止"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)", "git reset --hard / git clean -f は禁止"),
    (r"\bmkfs\b|\bdd\s+if=", "ディスク破壊コマンドは禁止"),
    (r"\bzip\b.*\b(raw|refs|review|SESSION\.md|three-view|meta|plan\.md)\b", "提出ZIPに写真・三面図・レビュー・SESSION・メタを入れない"),
    (r"\bchmod\s+-R\s+777\b", "chmod -R 777 は禁止"),
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") not in (None, "Bash"):
        return
    command = str(payload.get("tool_input", {}).get("command", ""))
    if not command:
        return
    for pattern, reason in DENY_PATTERNS:
        if re.search(pattern, command):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"[block-dangerous] {reason}: {command[:120]}",
                        }
                    },
                    ensure_ascii=False,
                )
            )
            return


if __name__ == "__main__":
    main()
