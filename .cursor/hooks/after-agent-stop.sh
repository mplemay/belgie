#!/usr/bin/env bash
# Cursor stop hook: after a completed agent turn with a dirty tree, run pytest and
# either nudge a fix or ask the agent to commit/push (prek runs on git commit).

set -euo pipefail

emit_empty() {
  printf '%s\n' '{}'
  exit 0
}

emit_followup() {
  # $1 = followup message text
  jq -n --arg msg "$1" '{followup_message: $msg}'
  exit 0
}

trap 'emit_empty' ERR

input="$(cat)"
status="$(printf '%s' "$input" | jq -r '.status // empty')"
loop_count="$(printf '%s' "$input" | jq -r '.loop_count // 0')"

if [[ "$status" != "completed" ]]; then
  emit_empty
fi

if [[ "$loop_count" -ge 5 ]]; then
  emit_empty
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  emit_empty
fi

# Dirty if there are staged, unstaged, or untracked (non-ignored) changes.
if git diff --quiet --ignore-submodules HEAD 2>/dev/null &&
  git diff --cached --quiet --ignore-submodules 2>/dev/null &&
  [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  emit_empty
fi

if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
else
  emit_followup "Working tree has uncommitted changes, but \`uv\` was not found. Install/enable uv, then fix any remaining issues and stop so commit/push can proceed."
fi

pytest_log="$(mktemp)"
trap 'rm -f "$pytest_log"; emit_empty' ERR

set +e
"$UV" run pytest >"$pytest_log" 2>&1
pytest_rc=$?
set -e

if [[ "$pytest_rc" -ne 0 ]]; then
  # Keep the follow-up bounded for the model context window.
  failure_tail="$(tail -n 80 "$pytest_log")"
  rm -f "$pytest_log"
  emit_followup "$(
    cat <<EOF
Tests failed after your changes (\`uv run pytest\` exit $pytest_rc). Fix the root cause, then stop — do not commit yet.

\`\`\`
$failure_tail
\`\`\`
EOF
  )"
fi

rm -f "$pytest_log"
trap 'emit_empty' ERR

emit_followup "$(
  cat <<'EOF'
Working tree is dirty and tests passed. Finish the change set:

1. Stage the relevant files (skip secrets such as `.env` / credentials).
2. Create a lowercase single-line conventional commit (e.g. `feat: ...`, `fix: ...`).
3. Do not use `--no-verify` or otherwise skip git hooks — `prek` must run on commit.
4. If `prek` autofixes and aborts the commit, re-stage and commit again.
5. `git push` to the tracked remote (no force push).

Then stop. If the tree is still dirty after a failed commit/push, the stop hook will nudge again.
EOF
)"
