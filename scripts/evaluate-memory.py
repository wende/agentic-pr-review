#!/usr/bin/env python3
"""Evaluate one durable memory candidate after a marked review is published."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REVIEW_MARKERS = (
    "<!-- agentic-pr-review -->",
    "<!-- macbeth-openhands-review -->",
)
MODEL_NO_CANDIDATE_REASONS = {
    "no_applied_feedback",
    "no_generalizable_lesson",
}
MAX_DIFF_CHARS = 80_000
MEMORY_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_memory_decision",
        "description": (
            "Record one validated repository-memory candidate or explain why "
            "none qualifies."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "decision_version": {
                    "type": "integer",
                    "enum": [1],
                },
                "decision": {
                    "type": "string",
                    "enum": ["candidate", "no_candidate"],
                },
                "source_comment_id": {"type": "integer"},
                "lesson": {"type": "string"},
                "original_concern": {"type": "string"},
                "applied_fix": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["path", "description"],
                        "additionalProperties": False,
                    },
                },
                "reason": {
                    "type": "string",
                    "enum": [
                        "no_applied_feedback",
                        "no_generalizable_lesson",
                    ],
                },
                "details": {"type": "string"},
            },
            "required": ["decision_version", "decision"],
            "additionalProperties": False,
        },
    },
}


def command(*args: str) -> str:
    return subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def gh_json(*args: str) -> Any:
    return json.loads(command("gh", "api", *args))


def flatten_pages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("GitHub API returned a non-list page")
    if value and all(isinstance(page, list) for page in value):
        return [item for page in value for item in page]
    return value


def is_marked(review: dict[str, Any]) -> bool:
    body = review.get("body") or ""
    return any(body.startswith(marker) for marker in REVIEW_MARKERS)


def ordered(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        reviews,
        key=lambda review: (
            review.get("submitted_at") or "",
            int(review.get("id") or 0),
        ),
    )


def write_decision(path: Path, decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Memory evaluation: "
        f"{decision['decision']} "
        f"({decision.get('reason', decision.get('source_comment_id', ''))})"
    )


def truncate_details(details: str) -> str:
    # `details` is schema-bound to 1-1000 characters, and an arbitrary exception
    # message can exceed that or be empty. Neutralize review markers too, so a
    # failure echoing repository content cannot forge one.
    cleaned = details.replace("<!--", "<!—").replace("-->", "—>").strip()
    if not cleaned:
        return "The memory evaluator failed without a message."
    return cleaned if len(cleaned) <= 1000 else cleaned[:997] + "..."


def no_candidate(reason: str, details: str) -> dict[str, Any]:
    return {
        "decision_version": 1,
        "decision": "no_candidate",
        "reason": reason,
        "details": details,
    }


def parse_model_json(content: str) -> dict[str, Any]:
    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise RuntimeError("memory evaluator returned no JSON object")
        try:
            parsed, _ = json.JSONDecoder().raw_decode(candidate[start:])
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "memory evaluator returned malformed JSON"
            ) from error
    if not isinstance(parsed, dict):
        raise RuntimeError("memory evaluator result must be a JSON object")
    return parsed


def clean_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"memory evaluator field {field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise RuntimeError(
            f"memory evaluator field {field} must contain 1-{maximum} characters"
        )
    if "<!--" in cleaned or "-->" in cleaned:
        raise RuntimeError(f"memory evaluator field {field} contains a marker")
    return cleaned


def validate_decision(
    decision: dict[str, Any],
    comment_ids: set[int],
    changed_paths: set[str],
) -> dict[str, Any]:
    if decision.get("decision_version") != 1:
        raise RuntimeError("memory evaluator returned an unsupported decision_version")

    kind = decision.get("decision")
    if kind == "no_candidate":
        reason = decision.get("reason")
        if reason not in MODEL_NO_CANDIDATE_REASONS:
            raise RuntimeError("memory evaluator returned an invalid no-candidate reason")
        return no_candidate(reason, clean_text(decision.get("details"), "details", 1000))

    if kind != "candidate":
        raise RuntimeError("memory evaluator decision must be candidate or no_candidate")

    source_comment_id = decision.get("source_comment_id")
    if (
        not isinstance(source_comment_id, int)
        or isinstance(source_comment_id, bool)
        or source_comment_id not in comment_ids
    ):
        raise RuntimeError(
            "memory candidate must reference an inline comment from the previous review"
        )

    evidence = decision.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 5:
        raise RuntimeError("memory candidate must contain 1-5 evidence items")

    normalized_evidence: list[dict[str, str]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise RuntimeError("memory evidence items must be objects")
        path = clean_text(item.get("path"), f"evidence[{index}].path", 500)
        if path not in changed_paths:
            raise RuntimeError(
                f"memory evidence path was not changed since the review: {path}"
            )
        normalized_evidence.append(
            {
                "path": path,
                "description": clean_text(
                    item.get("description"),
                    f"evidence[{index}].description",
                    1000,
                ),
            }
        )

    return {
        "decision_version": 1,
        "decision": "candidate",
        "source_comment_id": source_comment_id,
        "lesson": clean_text(decision.get("lesson"), "lesson", 1000),
        "original_concern": clean_text(
            decision.get("original_concern"),
            "original_concern",
            1500,
        ),
        "applied_fix": clean_text(
            decision.get("applied_fix"),
            "applied_fix",
            1500,
        ),
        "evidence": normalized_evidence,
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: evaluate-memory.py PATH_TO_PROMPT PATH_TO_DECISION_JSON"
        )

    prompt_path = Path(sys.argv[1]).resolve()
    decision_path = Path(sys.argv[2]).resolve()
    repository = os.environ.get("REPO_NAME", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    if not prompt_path.is_file():
        raise SystemExit(f"memory evaluator prompt not found: {prompt_path}")
    if not repository or not pr_number.isdigit():
        raise SystemExit("REPO_NAME and numeric PR_NUMBER are required")

    # The review is already published by the time this runs. Memory is an
    # enhancement layered on top of it, so a malformed model response, a
    # transient API failure, or an unexpected GitHub payload must degrade to
    # "no memory recorded" rather than failing the job and burying a review
    # that already succeeded.
    try:
        evaluate(prompt_path, decision_path, repository, pr_number)
    except Exception as error:
        details = f"{type(error).__name__}: {error}".strip()
        write_decision(
            decision_path,
            no_candidate("evaluation_failed", truncate_details(details)),
        )
        print(f"::warning::Memory evaluation failed, review unaffected: {details}")


def evaluate(
    prompt_path: Path,
    decision_path: Path,
    repository: str,
    pr_number: str,
) -> None:
    head_commit = command("git", "rev-parse", "HEAD").strip()
    reviews = flatten_pages(
        gh_json(
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls/{pr_number}/reviews?per_page=100",
        )
    )
    marked_reviews = ordered([review for review in reviews if is_marked(review)])
    current_reviews = [
        review for review in marked_reviews if review.get("commit_id") == head_commit
    ]
    if not current_reviews:
        raise RuntimeError(
            f"no marked review exists for current commit {head_commit}"
        )

    current_review = current_reviews[-1]
    current_index = next(
        index
        for index, review in enumerate(marked_reviews)
        if review.get("id") == current_review.get("id")
    )
    if current_index == 0:
        write_decision(
            decision_path,
            no_candidate(
                "no_previous_review",
                "This is the first marked review checkpoint for the pull request.",
            ),
        )
        return

    previous_review = marked_reviews[current_index - 1]
    comments = flatten_pages(
        gh_json(
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls/{pr_number}/comments?per_page=100",
        )
    )
    previous_review_id = int(previous_review["id"])
    reviewer_login = (previous_review.get("user") or {}).get("login")
    previous_comments = [
        comment
        for comment in comments
        if comment.get("pull_request_review_id") == previous_review_id
        and (comment.get("user") or {}).get("login") == reviewer_login
    ]
    if not previous_comments:
        write_decision(
            decision_path,
            no_candidate(
                "no_previous_inline_comments",
                "The previous marked review had no inline comments to evaluate.",
            ),
        )
        return

    previous_commit = str(previous_review["commit_id"])
    # Force-pushes leave prior review commit_ids orphaned in GitHub but absent
    # from the shallow checkout; git diff then exits 128. Skip evaluation rather
    # than failing the job — there is no reliable path set to verify applied fixes.
    try:
        changed_paths = {
            path
            for path in command(
                "git",
                "diff",
                "--name-only",
                previous_commit,
                head_commit,
                "--",
            ).splitlines()
            if path
        }
        diff = command(
            "git",
            "diff",
            "--no-ext-diff",
            "--unified=40",
            previous_commit,
            head_commit,
            "--",
        )
    except subprocess.CalledProcessError as error:
        if error.returncode != 128:
            raise
        write_decision(
            decision_path,
            no_candidate(
                "previous_commit_unavailable",
                "A review checkpoint commit is not in the local repository "
                "(history was rewritten, e.g. by force-push); cannot verify "
                "applied fixes against the previous review.",
            ),
        )
        return
    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS]
            + "\n\n[Diff truncated by the memory evaluator.]\n"
        )

    evaluation_input = {
        "pull_request": int(pr_number),
        "previous_review": {
            "id": previous_review_id,
            "commit_id": previous_commit,
            "submitted_at": previous_review.get("submitted_at"),
        },
        "previous_inline_comments": [
            {
                "id": int(comment["id"]),
                "path": comment.get("path"),
                "line": comment.get("line") or comment.get("original_line"),
                "body": (comment.get("body") or "")[:3000],
                "url": comment.get("html_url"),
            }
            for comment in previous_comments[:25]
        ],
        "current_commit": head_commit,
        "changed_paths": sorted(changed_paths),
        "changes_since_previous_review": diff,
    }

    from litellm import completion

    response = completion(
        model=os.environ["LLM_MODEL"],
        api_base=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        messages=[
            {
                "role": "system",
                "content": prompt_path.read_text(encoding="utf-8"),
            },
            {
                "role": "user",
                "content": json.dumps(evaluation_input, ensure_ascii=False),
            },
        ],
        temperature=0,
        max_tokens=1400,
        timeout=120,
        num_retries=0,
        tools=[MEMORY_DECISION_TOOL],
        tool_choice={
            "type": "function",
            "function": {"name": "record_memory_decision"},
        },
    )
    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        tool_call = tool_calls[0]
        function = getattr(tool_call, "function", None)
        if (
            function is None
            or getattr(function, "name", None) != "record_memory_decision"
        ):
            raise RuntimeError("memory evaluator called an unexpected tool")
        content = getattr(function, "arguments", None)
    else:
        # Preserve compatibility with providers that obey the JSON-only prompt
        # but do not implement forced OpenAI-compatible tool choice.
        content = message.content
    if not isinstance(content, str):
        raise RuntimeError("memory evaluator returned no decision")
    decision = validate_decision(
        parse_model_json(content),
        {int(comment["id"]) for comment in previous_comments},
        changed_paths,
    )
    write_decision(decision_path, decision)


if __name__ == "__main__":
    main()
