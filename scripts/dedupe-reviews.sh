#!/usr/bin/env bash
set -euo pipefail

repository="${1:?GitHub repository is required}"
pr_number="${2:?pull request number is required}"
head_commit="${3:?current head commit is required}"
review_marker='<!-- agentic-pr-review -->'
legacy_marker='<!-- macbeth-openhands-review -->'
superseded_marker='<!-- agentic-pr-review-superseded -->'

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::github-token is required to collapse duplicate reviews"
  exit 1
fi
if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
  [[ ! "$pr_number" =~ ^[1-9][0-9]*$ ]] ||
  [[ ! "$head_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::Invalid review deduplication identifiers"
  exit 1
fi

# Only marked bot reviews on the current head are ours to touch. An unmarked
# bot review at the same commit belongs to some other workflow, and a marked
# review at an older commit is a real checkpoint the follow-up protocol reads.
marked_ids="$(
  gh api --paginate --slurp \
    "repos/${repository}/pulls/${pr_number}/reviews?per_page=100" |
    jq -c \
      --arg head "$head_commit" \
      --arg marker "$review_marker" \
      --arg legacy "$legacy_marker" '
      (if length > 0 and (.[0] | type) == "array" then add else . end)
      | map(select(
          .commit_id == $head and
          .user.login == "github-actions[bot]" and
          ((.body // "") | startswith($marker) or startswith($legacy))
        ))
      | map(.id)
      | sort
    '
)"
# Keep the newest, which is the one ensure-review-marker.sh verified. A rerun
# on an unchanged head collapses the earlier run's review too, so the pull
# request carries one readable review body per commit rather than one per run.
kept="$(jq -r 'last // empty' <<<"$marked_ids")"
if [[ -z "$kept" ]]; then
  echo "No marked review to deduplicate for $head_commit"
  exit 0
fi

superseded_body="$(
  printf '%s\n\n' "$superseded_marker"
  printf 'Duplicate of review #%s on the same commit. The body was collapsed to keep the pull request readable.\n' \
    "$kept"
)"
collapsed=0
for review_id in $(jq -r '.[:-1][]' <<<"$marked_ids"); do
  # The superseded marker deliberately replaces the review marker so a later
  # run does not read a collapsed duplicate as its follow-up checkpoint.
  jq -cn --arg body "$superseded_body" '{body: $body}' |
    gh api \
      -X PUT \
      "repos/${repository}/pulls/${pr_number}/reviews/${review_id}" \
      --input - >/dev/null
  echo "Collapsed duplicate review #${review_id} superseded by #${kept}"
  collapsed=$((collapsed + 1))
done

# Inline comments are matched through pull_request_review_id, so only comments
# submitted by the reviews above are candidates. Within a group of identical
# comments the earliest survives, because that is the one an author is most
# likely to have replied to. Any comment carrying a reply is kept regardless:
# losing a thread the author engaged with is worse than leaving a duplicate.
# The reply set is read from every comment on the pull request, since author
# replies belong to the author's own review, not to ours.
duplicate_comment_ids="$(
  gh api --paginate --slurp \
    "repos/${repository}/pulls/${pr_number}/comments?per_page=100" |
    jq -r --argjson reviews "$marked_ids" '
      (if length > 0 and (.[0] | type) == "array" then add else . end)
      | . as $all
      | ($all | map(.in_reply_to_id) | map(select(. != null))) as $answered
      | $all
      | map(select(
          (.pull_request_review_id as $review | $reviews | index($review)) and
          .in_reply_to_id == null
        ))
      | group_by([.path, (.line // .original_line), (.side // "RIGHT"), .body])
      | map(
          sort_by(.id)
          | .[1:]
          | map(select(.id as $comment | ($answered | index($comment)) | not))
        )
      | add // []
      | .[].id
    '
)"
deleted=0
for comment_id in $duplicate_comment_ids; do
  gh api -X DELETE "repos/${repository}/pulls/comments/${comment_id}" >/dev/null
  echo "Deleted duplicate review comment #${comment_id}"
  deleted=$((deleted + 1))
done

echo "Kept review #${kept} for ${head_commit}: collapsed ${collapsed} duplicate review(s), deleted ${deleted} duplicate comment(s)"
