#!/usr/bin/env bash
# UserPromptSubmit hook: inject the current gate of the active project so the agent never skips gates.
# Prints a selection reminder when no project is active. Never fails the prompt.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-.}"
ACTIVE_FILE="$ROOT/projects/ACTIVE"
if [ ! -f "$ACTIVE_FILE" ]; then
  if ls "$ROOT"/projects/*/SESSION.md >/dev/null 2>&1; then
    printf '[gate-reminder] ACTIVE=none — 進行中プロジェクトがある。制作作業の前に選択か新規作成を選択肢で確認する。\n'
  fi
  exit 0
fi
slug=$(tr -d '[:space:]' < "$ACTIVE_FILE")
SESSION="$ROOT/projects/$slug/SESSION.md"
[ -f "$SESSION" ] || { printf '[gate-reminder] ACTIVE=%s だが SESSION.md がない。project.py list で確認する。\n' "$slug"; exit 0; }
gate=$(grep -E '^- gate:' "$SESSION" | head -1 | sed 's/^- gate: *//')
submission=$(grep -E '^- submission:' "$SESSION" | head -1 | sed 's/^- submission: *//')
[ -n "$gate" ] || exit 0
printf '[gate-reminder] project=%s gate=%s submission=%s — このゲートの承認を得るまで次へ進まない。承認語はOK/続けて/いいね/それで。\n' "$slug" "$gate" "$submission"
exit 0
