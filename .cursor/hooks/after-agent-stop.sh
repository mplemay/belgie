#!/usr/bin/env bash
# Cursor stop hook: after a completed agent turn, run pytest on a dirty tree and
# nudge commit/push (prek runs on git commit). On main/master, require a feature
# branch first; recover unpushed commits already sitting on those branches.

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

branch="$(git rev-parse --abbrev-ref HEAD)"
protected=0
case "$branch" in
main | master) protected=1 ;;
esac

tree_dirty=1
if git diff --quiet --ignore-submodules HEAD 2>/dev/null &&
  git diff --cached --quiet --ignore-submodules 2>/dev/null &&
  [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  tree_dirty=0
fi

protected_remote="origin"
protected_upstream="origin/${branch}"
if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
  protected_remote="${upstream%%/*}"
  protected_upstream="$upstream"
fi

ahead_count=0
if [[ "$protected" -eq 1 ]] && git rev-parse --verify --quiet "$protected_upstream" >/dev/null; then
  ahead_count="$(git rev-list --count "${protected_upstream}..HEAD")"
fi

if [[ "$tree_dirty" -eq 0 ]]; then
  if [[ "$protected" -eq 1 && "$ahead_count" -gt 0 ]]; then
    emit_followup "$(
      cat <<EOF
Commit(s) are on \`${branch}\` and cannot be pushed (direct pushes are blocked). Move them onto a feature branch:

1. Checkout a new lowercase conventional branch from current HEAD (e.g. \`feat/short-description\`).
2. Reset local \`${branch}\` to \`${protected_upstream}\`: \`git branch --force ${branch} ${protected_upstream}\` (after checkout; do not force-push).
3. \`git push -u ${protected_remote} HEAD\` (no force push).
4. Open a PR with \`gh pr create\` (title from the commit; body with Summary + Test plan).

Then stop.
EOF
    )"
  fi
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

if [[ "$protected" -eq 1 ]]; then
  emit_followup "$(
    cat <<EOF
Working tree is dirty and tests passed. You are on \`${branch}\` (direct pushes are blocked). Finish the change set:

1. Checkout a new lowercase conventional branch first (e.g. \`feat/short-description\`). Do not commit on \`${branch}\`.
2. Stage the relevant files (skip secrets such as \`.env\` / credentials).
3. Create a lowercase single-line conventional commit (e.g. \`feat: ...\`, \`fix: ...\`).
4. Do not use \`--no-verify\` or otherwise skip git hooks — \`prek\` must run on commit.
5. If \`prek\` autofixes and aborts the commit, re-stage and commit again.
6. \`git push -u ${protected_remote} HEAD\` (no force push).
7. Open a PR with \`gh pr create\` (title from the commit; body with Summary + Test plan).

Then stop. If the tree is still dirty after a failed commit/push, the stop hook will nudge again.
EOF
  )"
fi

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
