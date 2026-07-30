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

After the marker, begin the top-level review body with a concise
`Previous review follow-up` section. List resolved, still-present, and obsolete
findings, or state that the previous review had no actionable findings. Follow
it with a `New findings` section. On the first marked review, say so briefly and
omit the classification.

Do not post a duplicate inline comment for an unchanged, still-present finding;
reference it in the follow-up summary. Post inline comments for new findings,
materially changed failure modes, or incomplete fixes that need new evidence.
Read other reviewers' comments too and do not duplicate still-relevant findings.

Only report findings caused by the pull request that the author can act on.
Include concrete evidence: affected path and line, the triggering execution
path or scenario, and the user-visible consequence. Do not modify the
repository; this is a review-only task.
