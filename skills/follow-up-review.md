---
name: agentic-review-follow-up
description: Track findings across automatic pull request review reruns
triggers:
  - /codereview
---

# Follow-up review protocol

Review the complete pull request against its base branch on every run. The
changed-file manifest is the source of truth, but inspect full files, callers,
tests, and related definitions in the checked-out repository whenever context
could change a finding.

Every submitted review body must begin with this exact hidden marker:

`<!-- agentic-pr-review -->`

For migration, a review beginning with `<!-- macbeth-openhands-review -->` also
counts as a previous review checkpoint.

When a previous completed marked review exists, treat the most recent one as the
checkpoint while still examining the complete current pull request:

1. Re-check every actionable finding from that review and its associated
   threads against the current HEAD.
2. Classify each as **resolved**, **still present**, or **obsolete** because the
   affected code no longer exists. Never infer resolution solely from a
   resolved or outdated GitHub thread; verify the current code.
3. Check whether an attempted correction introduced a regression or incomplete
   fix. Treat that as a new finding and explain its relationship to the earlier
   one.
4. Find genuinely new issues across all current PR changes, including
   interactions between recent commits and older changes in the same PR.

Keep the review layout the code review instructions already define: taste
rating, then the issue sections, then the risk assessment and verdict. Add one
`Previous review follow-up` section directly after the taste rating. Settled
work is counted, not re-narrated, so this section stays short as a pull request
accumulates reruns:

- one line counting findings that are now resolved or obsolete, naming none of
  them individually and describing none of the fixes;
- one line counting findings the author has declined or deferred, naming none
  of them individually;
- the still present findings the author has not answered, at most one short
  line each.

Report the findings themselves in the sections that layout already provides; do
not add a separate list for them. On the first marked review, say so briefly and
omit the classification. When the previous review had no actionable findings,
say that in one line.

An author reply that rejects, defers, or accepts a finding is a standing
decision for this pull request. Count it once and then leave it alone: do not
restate it, do not re-argue it, and do not post another inline comment about it,
on this run or any later one. Raise it again only when new commits change the
code it covered, and say what changed.

Do not post a duplicate inline comment for an unchanged, still present finding;
reference it in the follow-up summary. Post inline comments for new findings,
materially changed failure modes, or incomplete fixes that need new evidence.
Read other reviewers' comments too and do not duplicate still-relevant findings.

## Publishing the review

Publish exactly once. Submit the body and every inline comment in a single
`POST /repos/{owner}/{repo}/pulls/{number}/reviews` call.

That response carries no `comments` array. A zero comment count in it is how
the endpoint always answers; it is not evidence that GitHub rejected the inline
comments. Never conclude from the response alone that a post failed.

Before acting on any suspicion that comments are missing, list what exists with
`GET /repos/{owner}/{repo}/pulls/{number}/comments`. If comments really are
missing, add only those with
`POST /repos/{owner}/{repo}/pulls/{number}/comments`. Never post a second
review carrying the same body: duplicate bodies are the single worst outcome
for a pull request's readability, worse than a missing inline comment.

## Execution budget

Use the normal investigation window efficiently:

- Start from the supplied changed-file manifest and diff. Batch related file
  reads, searches, and checks into a single tool action when practical.
- Do not reread a file, repeat a search, or rerun a check unless new evidence
  invalidated the earlier result.
- Inspect dependency implementation only when the changed code relies on an
  uncertain contract that repository code, documentation, and tests cannot
  establish.

The runtime will send an environment wrap-up message when the normal
investigation window is exhausted. Treat that message as a hard phase change:
stop all investigation, do not inspect any more repository or dependency
content, and do not run more tests or delegate. Use the remaining grace period
only to compose, validate, and submit the best evidence-backed marked review
supported by work already completed. The review is not complete until that
marked review is posted, and it is finished the moment the post returns a
review ID. Stop there; do not verify, re-post, or investigate further.

Only report findings caused by the pull request that the author can act on.
Include concrete evidence: affected path and line, the triggering execution
path or scenario, and the user-visible consequence. Do not modify the
repository; this is a review-only task.
