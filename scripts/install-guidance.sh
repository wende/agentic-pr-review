#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:?consumer repository directory is required}"
followup_skill="${2:?follow-up skill path is required}"
guidance_path="${3:-}"
skills_dir="$repo_dir/.agents/skills"

mkdir -p "$skills_dir"
install -m 0644 "$followup_skill" "$skills_dir/agentic-review-follow-up.md"

if [[ -z "$guidance_path" ]]; then
  exit 0
fi

if [[ "$guidance_path" == /* ]] || [[ "/$guidance_path/" == *"/../"* ]]; then
  echo "::error::review-guidance-path must stay inside the consumer repository"
  exit 1
fi

guidance_file="$repo_dir/$guidance_path"
if [[ ! -f "$guidance_file" ]]; then
  echo "::error::Review guidance file not found: $guidance_path"
  exit 1
fi

repo_root="$(realpath "$repo_dir")"
guidance_file="$(realpath "$guidance_file")"
if [[ "$guidance_file" != "$repo_root/"* ]]; then
  echo "::error::review-guidance-path resolves outside the consumer repository"
  exit 1
fi

{
  echo '---'
  echo 'name: repository-review-best-practices'
  echo 'description: Additional review rules supplied by this repository'
  echo 'triggers:'
  echo '  - /codereview'
  echo '---'
  echo
  echo '# Repository review best practices'
  echo
  sed 's/\r$//' "$guidance_file"
} > "$skills_dir/repository-review-best-practices.md"
