#!/usr/bin/env bash
set -euo pipefail

decision_path="${1:?memory decision path is required}"
repository="${2:?GitHub repository is required}"
pr_number="${3:?pull request number is required}"
issue_number="${4:?memory issue number is required}"
head_commit="${5:?current head commit is required}"
review_marker='<!-- agentic-pr-review -->'
legacy_review_marker='<!-- macbeth-openhands-review -->'
entry_marker='<!-- agentic-pr-review-memory-entry -->'

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::github-token is required to publish repository memory"
  exit 1
fi
if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "::error::Invalid GitHub repository: $repository"
  exit 1
fi
if [[ ! "$pr_number" =~ ^[1-9][0-9]*$ ]] ||
  [[ ! "$issue_number" =~ ^[1-9][0-9]*$ ]] ||
  [[ ! "$head_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::Invalid memory publication identifiers"
  exit 1
fi
if [[ ! -f "$decision_path" ]]; then
  echo "::error::Memory evaluator did not produce a decision"
  exit 1
fi

decision="$(jq -r '.decision // empty' "$decision_path")"
if [[ "$decision" == "no_candidate" ]]; then
  if ! jq -e '
    .decision_version == 1 and
    .decision == "no_candidate" and
    (
      .reason == "no_previous_review" or
      .reason == "no_previous_inline_comments" or
      .reason == "previous_commit_unavailable" or
      .reason == "no_applied_feedback" or
      .reason == "no_generalizable_lesson"
    ) and
    (.details | type == "string" and length > 0 and length <= 1000)
  ' "$decision_path" >/dev/null; then
    echo "::error::Invalid no-candidate memory decision"
    exit 1
  fi
  echo "Repository memory unchanged: $(jq -r '.reason' "$decision_path")"
  exit 0
fi

if [[ "$decision" != "candidate" ]]; then
  echo "::error::Memory decision must be candidate or no_candidate"
  exit 1
fi
if ! jq -e '
  .decision_version == 1 and
  .decision == "candidate" and
  (.source_comment_id | type == "number" and . > 0 and floor == .) and
  (.lesson | type == "string" and length > 0 and length <= 1000) and
  (.original_concern | type == "string" and length > 0 and length <= 1500) and
  (.applied_fix | type == "string" and length > 0 and length <= 1500) and
  (.evidence | type == "array" and length > 0 and length <= 5) and
  all(.evidence[];
    (.path | type == "string" and length > 0 and length <= 500) and
    (.description | type == "string" and length > 0 and length <= 1000)
  ) and
  ([.lesson, .original_concern, .applied_fix, .evidence[].path,
    .evidence[].description] |
    all(.[]; (contains("<!--") or contains("-->")) | not))
' "$decision_path" >/dev/null; then
  echo "::error::Invalid candidate memory decision"
  exit 1
fi

reviews_json="$(
  gh api --paginate --slurp \
    "repos/${repository}/pulls/${pr_number}/reviews?per_page=100"
)"
previous_review="$(
  jq -c \
    --arg head "$head_commit" \
    --arg marker "$review_marker" \
    --arg legacy "$legacy_review_marker" '
      (if length > 0 and (.[0] | type) == "array" then add else . end)
      | map(select(
          (
            ((.body // "") | startswith($marker)) or
            ((.body // "") | startswith($legacy))
          )
        ))
      | sort_by(.submitted_at, .id)
      | . as $marked
      | ($marked | map(select(.commit_id == $head)) | last // empty) as $current
      | ($marked | map(.id) | index($current.id)) as $current_index
      | if $current_index == null or $current_index == 0
        then empty
        else $marked[$current_index - 1]
        end
    ' <<<"$reviews_json"
)"
if [[ -z "$previous_review" ]]; then
  echo "::error::Candidate memory has no previous marked review checkpoint"
  exit 1
fi

source_comment_id="$(jq -r '.source_comment_id' "$decision_path")"
source_comment="$(
  gh api "repos/${repository}/pulls/comments/${source_comment_id}"
)"
previous_review_id="$(jq -r '.id' <<<"$previous_review")"
previous_reviewer="$(jq -r '.user.login' <<<"$previous_review")"
if ! jq -e \
  --argjson review_id "$previous_review_id" \
  --arg reviewer "$previous_reviewer" \
  --arg suffix "/pulls/${pr_number}" '
    .pull_request_review_id == $review_id and
    .user.login == $reviewer and
    (.pull_request_url | endswith($suffix))
  ' <<<"$source_comment" >/dev/null; then
  echo "::error::Memory candidate does not reference the previous marked review"
  exit 1
fi

previous_commit="$(jq -r '.commit_id' <<<"$previous_review")"
changed_paths_json="$(
  git diff --name-only -z "$previous_commit" "$head_commit" -- |
    jq -Rs 'split("\u0000") | map(select(length > 0))'
)"
if ! jq -e --argjson changed "$changed_paths_json" '
  all(.evidence[].path; . as $path | $changed | index($path) != null)
' "$decision_path" >/dev/null; then
  echo "::error::Memory evidence must reference files changed since the review"
  exit 1
fi

source_marker="<!-- agentic-pr-review-source-comment:${source_comment_id} -->"
comments_json="$(
  gh api --paginate --slurp \
    "repos/${repository}/issues/${issue_number}/comments?per_page=100"
)"
if jq -e --arg marker "$source_marker" '
  (if length > 0 and (.[0] | type) == "array" then add else . end)
  | any((.body // "") | contains($marker))
' <<<"$comments_json" >/dev/null; then
  echo "Repository memory already records review comment #${source_comment_id}"
  exit 0
fi

lesson="$(jq -r '.lesson' "$decision_path")"
original_concern="$(jq -r '.original_concern' "$decision_path")"
applied_fix="$(jq -r '.applied_fix' "$decision_path")"
evidence="$(
  jq -r '.evidence[] | "- `" + .path + "` — " + .description' "$decision_path"
)"
source_url="$(jq -r '.html_url' <<<"$source_comment")"
confirmed_date="$(date -u +%F)"
short_commit="${head_commit:0:12}"
memory_entry="$(
  printf "%s\n%s\n\n### Lesson\n\n%s\n\n### Confirmed application\n\n**Original concern:** %s\n\n**Applied fix:** %s\n\n**Evidence:**\n%s\n\n**Source:** PR #%s, [review comment #%s](%s), confirmed at commit \`%s\` on %s." \
    "$entry_marker" \
    "$source_marker" \
    "$lesson" \
    "$original_concern" \
    "$applied_fix" \
    "$evidence" \
    "$pr_number" \
    "$source_comment_id" \
    "$source_url" \
    "$short_commit" \
    "$confirmed_date"
)"

gh api -X POST \
  "repos/${repository}/issues/${issue_number}/comments" \
  -f body="$memory_entry" >/dev/null
echo "Published repository memory from review comment #${source_comment_id}"
