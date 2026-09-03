#!/usr/bin/env bash
# SessionStart hook: list existing projects so the agent offers "resume or create" before any production work.
# Never fails the session.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-.}"
PROJECT_PY="$ROOT/.claude/skills/line-stamp-generator/scripts/project.py"
[ -f "$PROJECT_PY" ] || exit 0
listing=$(python3 "$PROJECT_PY" --root "$ROOT" list 2>/dev/null)
active=$(cat "$ROOT/projects/ACTIVE" 2>/dev/null | tr -d '[:space:]')
printf '[session-start] projects:\n%s\n' "$listing"
if [ -n "$active" ]; then
  printf '[session-start] ACTIVE=%s — 制作依頼を受けたら「このプロジェクトを続ける / 別を選ぶ / 新規作成」を選択肢で確認してから進める。\n' "$active"
else
  printf '[session-start] ACTIVE=none — 制作依頼を受けたら、進行中プロジェクトの選択か新規作成を選択肢で提示し、確定するまでゲートを進めない。\n'
fi
exit 0
