#!/usr/bin/env bash
# Claude compatibility wrapper. Gate-state logic lives in scripts/hooks/project_context.mjs.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-.}"
node "$ROOT/scripts/hooks/project_context.mjs" claude prompt "$ROOT" || exit 0
