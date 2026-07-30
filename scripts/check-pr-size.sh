#!/usr/bin/env bash
set -euo pipefail

additions="${1:?additions count is required}"
deletions="${2:?deletions count is required}"
max_changed_lines="${3:?max-changed-lines is required}"

for count in "$additions" "$deletions"; do
  if [[ ! "$count" =~ ^[0-9]+$ ]]; then
    echo "::error::Pull request line counts must be non-negative integers"
    exit 1
  fi
done

if [[ ! "$max_changed_lines" =~ ^[0-9]+$ ]]; then
  echo "::error::max-changed-lines must be a non-negative integer"
  exit 1
fi

changed_lines=$((additions + deletions))
oversized=false
if ((max_changed_lines > 0)) && ((changed_lines > max_changed_lines)); then
  oversized=true
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    printf 'changed-lines=%s\n' "$changed_lines"
    printf 'oversized=%s\n' "$oversized"
  } >>"$GITHUB_OUTPUT"
fi

printf 'Changed lines: %s (limit: %s, oversized: %s)\n' \
  "$changed_lines" "$max_changed_lines" "$oversized"
