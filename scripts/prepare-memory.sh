#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:?consumer repository directory is required}"
memory_skill="${2:?repository memory skill path is required}"
repository="${3:?GitHub repository is required}"
requested_issue_number="${4:-}"
memory_title='[agentic-pr-review] Repository memory'
memory_marker='<!-- agentic-pr-review-memory -->'
entry_marker='<!-- agentic-pr-review-memory-entry -->'
output_file="$repo_dir/.agents/skills/agentic-review-repository-memory.md"

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::github-token is required to prepare repository memory"
  exit 1
fi

if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "::error::Invalid GitHub repository: $repository"
  exit 1
fi

if [[ -n "$requested_issue_number" ]] &&
  [[ ! "$requested_issue_number" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::memory-issue-number must be a positive integer"
  exit 1
fi

if [[ ! -f "$memory_skill" ]]; then
  echo "::error::Repository memory skill not found: $memory_skill"
  exit 1
fi

issue_number="$requested_issue_number"
if [[ -z "$issue_number" ]]; then
  issues_json="$(
    gh api --paginate --slurp \
      "repos/${repository}/issues?state=all&per_page=100"
  )"
  issue_number="$(
    jq -r --arg title "$memory_title" '
      (if length > 0 and (.[0] | type) == "array" then add else . end)
      | map(select((has("pull_request") | not) and .title == $title))
      | sort_by(.number)
      | first
      | .number // empty
    ' <<<"$issues_json"
  )"
fi

if [[ -z "$issue_number" ]]; then
  initial_body="$memory_marker
# Repository review memory

This issue stores durable, repository-scoped knowledge for Agentic PR Review.
The reviewer appends marked memory entries as comments. Do not close or delete
this issue while repository memory is enabled.

Do not store secrets, personal data, unconfirmed pull request claims, or
one-off findings here."
  created_issue="$(
    gh api -X POST "repos/${repository}/issues" \
      -f title="$memory_title" \
      -f body="$initial_body"
  )"
  issue_number="$(jq -r '.number' <<<"$created_issue")"
fi

issue_json="$(gh api "repos/${repository}/issues/${issue_number}")"
if [[ "$(jq -r 'has("pull_request")' <<<"$issue_json")" == "true" ]]; then
  echo "::error::memory-issue-number must identify an issue, not a pull request"
  exit 1
fi

issue_body="$(jq -r '.body // ""' <<<"$issue_json")"
if [[ "$issue_body" != *"$memory_marker"* ]]; then
  echo "::error::Memory issue #${issue_number} is missing $memory_marker"
  exit 1
fi

comments_json="$(
  gh api --paginate --slurp \
    "repos/${repository}/issues/${issue_number}/comments?per_page=100"
)"
trusted_entries="$(
  jq -r --arg marker "$entry_marker" '
    (if length > 0 and (.[0] | type) == "array" then add else . end)
    | map(select(
        (((.body // "") | startswith($marker))) and
        (
          .author_association == "OWNER" or
          .author_association == "MEMBER" or
          .author_association == "COLLABORATOR" or
          .user.type == "Bot"
        )
      ))
    | sort_by(.created_at)
    | if length > 100 then .[-100:] else . end
    | .[]
    | "### \(.created_at) — @\(.user.login)\n\n\(.body)\n"
  ' <<<"$comments_json"
)"

mkdir -p "$(dirname "$output_file")"
install -m 0644 "$memory_skill" "$output_file"
{
  echo
  echo '## Memory source'
  echo
  echo "- Repository: \`$repository\`"
  echo "- Issue: [#$issue_number]($(jq -r '.html_url' <<<"$issue_json"))"
  echo
  echo '## Maintainer-owned memory policy'
  echo
  printf '%s\n' "$issue_body"
  echo
  echo '## Accepted memory entries'
  echo
  if [[ -n "$trusted_entries" ]]; then
    printf '%s\n' "$trusted_entries"
  else
    echo 'No accepted memory entries have been recorded yet.'
  fi
} >>"$output_file"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "issue-number=$issue_number"
    echo "issue-url=$(jq -r '.html_url' <<<"$issue_json")"
  } >>"$GITHUB_OUTPUT"
fi

echo "Prepared repository memory from issue #${issue_number}"
