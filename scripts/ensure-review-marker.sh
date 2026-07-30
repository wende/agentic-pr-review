#!/usr/bin/env bash
set -euo pipefail

repository="${1:?GitHub repository is required}"
pr_number="${2:?pull request number is required}"
head_commit="${3:?current head commit is required}"
previous_review_id="${4:?previous review ID is required}"
review_marker='<!-- agentic-pr-review -->'

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::github-token is required to verify the agentic review"
  exit 1
fi
if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
  [[ ! "$pr_number" =~ ^[1-9][0-9]*$ ]] ||
  [[ ! "$head_commit" =~ ^[0-9a-f]{40}$ ]] ||
  [[ ! "$previous_review_id" =~ ^[0-9]+$ ]]; then
  echo "::error::Invalid review verification identifiers"
  exit 1
fi

reviews_json="$(
  gh api --paginate --slurp \
    "repos/${repository}/pulls/${pr_number}/reviews?per_page=100"
)"
review="$(
  jq -c \
    --arg head "$head_commit" \
    --argjson previous "$previous_review_id" '
      (if length > 0 and (.[0] | type) == "array" then add else . end)
      | map(select(
          .commit_id == $head and
          .user.login == "github-actions[bot]" and
          .id > $previous
        ))
      | sort_by(.id)
      | last // empty
    ' <<<"$reviews_json"
)"
if [[ -z "$review" ]]; then
  echo "::error::Agent exited without posting a new review for $head_commit"
  exit 1
fi

review_id="$(jq -r '.id' <<<"$review")"
review_body="$(jq -r '.body // ""' <<<"$review")"
if [[ "$review_body" != "$review_marker"* ]]; then
  marked_body="$review_marker"
  if [[ -n "$review_body" ]]; then
    marked_body+=$'\n\n'
    marked_body+="$review_body"
  fi
  jq -n --arg body "$marked_body" '{body: $body}' |
    gh api \
      -X PUT \
      "repos/${repository}/pulls/${pr_number}/reviews/${review_id}" \
      --input - >/dev/null
  echo "Added the agentic review marker to review #${review_id}"
fi

verified_review="$(
  gh api "repos/${repository}/pulls/${pr_number}/reviews/${review_id}"
)"
if ! jq -e \
  --arg head "$head_commit" \
  --arg marker "$review_marker" \
  --argjson previous "$previous_review_id" '
    .commit_id == $head and
    .user.login == "github-actions[bot]" and
    .id > $previous and
    ((.body // "") | startswith($marker))
  ' <<<"$verified_review" >/dev/null; then
  echo "::error::Review #${review_id} failed marker verification"
  exit 1
fi

echo "Verified marked review #${review_id} for $head_commit"
