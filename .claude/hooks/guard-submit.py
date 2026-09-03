#!/usr/bin/env python3
"""PreToolUse hook for browser/MCP tools: deny irreversible LINE Creators Market actions and credential entry.

Tool-agnostic: inspects the whole tool_input JSON as text, so it works with any browser automation
tool (extension, MCP server, CLI wrapper) as long as the click target or typed text appears in the input.
"""
from __future__ import annotations

import json
import re
import sys

IRREVERSIBLE = (
    r"審査をリクエスト", r"審査リクエスト", r"request\s*review", r"submit\s*for\s*review",
    r"リリース", r"\brelease\b", r"販売開始", r"start\s*sales",
    r"削除", r"\bdelete\b", r"販売停止", r"公開停止",
)
CREDENTIAL_FIELDS = (r"password", r"パスワード", r"passcode", r"認証コード", r"verification\s*code", r"otp", r"pin\b")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    if tool_name in ("Bash", "Read", "Write", "Edit", "Glob", "Grep"):
        return
    blob = json.dumps(tool_input, ensure_ascii=False).lower()
    if "creator.line.me" not in blob and "line creators" not in blob and "creators market" not in blob and "sticker" not in blob and "スタンプ" not in blob:
        # Only guard when the action is plausibly on the Creators Market flow; otherwise stay out of the way.
        # Credential fields are guarded regardless of site.
        for pattern in CREDENTIAL_FIELDS:
            if re.search(pattern, blob):
                deny(f"認証情報の入力は禁止（{pattern}）。ログインはユーザー本人が行う")
                return
        return
    for pattern in IRREVERSIBLE:
        if re.search(pattern, blob):
            deny(f"不可逆操作「{pattern}」はユーザー本人が押す。入力内容のサマリを提示して停止する")
            return
    for pattern in CREDENTIAL_FIELDS:
        if re.search(pattern, blob):
            deny(f"認証情報の入力は禁止（{pattern}）。ログインはユーザー本人が行う")
            return


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"[guard-submit] {reason}",
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
