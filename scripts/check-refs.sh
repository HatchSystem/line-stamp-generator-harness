#!/usr/bin/env bash
# Check that file paths referenced in AGENTS.md, CLAUDE.md, README.md, rules, agents, and the skill exist.
set -u
cd "$(dirname "$0")/.."
status=0
targets="AGENTS.md CLAUDE.md README.md $(ls .claude/rules/*.md .claude/agents/*.md .claude/skills/*/SKILL.md .claude/skills/line-stamp-generator/references/*.md 2>/dev/null)"
for file in $targets; do
  dir=$(dirname "$file")
  # candidates: @path, backticked paths, markdown link targets
  refs=$( { grep -oE '@[A-Za-z0-9_./-]+\.(md|py|sh|json)' "$file" | sed 's/^@//'; \
            grep -oE '`[A-Za-z0-9_./-]+\.(md|py|sh|json|template)`' "$file" | tr -d '`'; \
            grep -oE '\]\([A-Za-z0-9_./-]+\.(md|json)\)' "$file" | sed 's/^](//; s/)$//'; } | sort -u )
  for ref in $refs; do
    case "$ref" in
      # runtime-generated, gitignored, or placeholder paths
      *NN*|*YYYY*|*\<*|manifest.json|*submission.json|*SESSION.md|plan.md|lock.md|bad.json|projects/*|tasks/todo.md|settings.local.json) continue ;;
    esac
    if [ -e "$ref" ] || [ -e "$dir/$ref" ] || [ -e ".claude/skills/line-stamp-generator/$ref" ] || [ -e ".claude/skills/line-stamp-generator/scripts/$ref" ] || [ -e ".claude/skills/line-stamp-generator/references/$ref" ] || [ -e ".claude/$ref" ] || [ -e ".claude/hooks/$ref" ]; then
      continue
    fi
    echo "MISSING $file -> $ref"
    status=1
  done
done
[ $status -eq 0 ] && echo "check-refs: OK"
exit $status
