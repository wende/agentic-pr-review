# Changelog

## Unreleased

## 1.1.0 - 2026-07-30

- Add persistent repository review memory backed by a GitHub issue.
- Evaluate memory in a separate post-review model phase and publish only
  validated structured decisions.
- Add a self-review workflow using the repository's memory issue.
- Supply MiniMax prices to telemetry without changing its OpenAI-compatible request path.
- Steer the coordinator to publish after 40 iterations and enforce a hard
  60-iteration ceiling.
- Verify that the current run publishes a new marked review.
- Remove the unused reaction-based review feedback footer.
- Explain permission-preflight failures without overclaiming the cause: name
  the usual `pull-requests: write` fix, surface `gh`'s stderr, and name the
  leftover review ID when cleanup fails.
- Skip the review and comment on the pull request when additions plus deletions
  exceed `max-changed-lines` (default `10000`; `0` disables). The check runs
  before the checkouts. The notice is edited in place while oversized, and
  deleted when the PR later drops under the limit.
- Memory evaluation records `previous_commit_unavailable` instead of failing
  when a prior review commit is missing after a force-push.
- Standardize follow-up vocabulary on `still present` (two words, no hyphen).
- Stop passing `REVIEW_STYLE`, `ACP_COMMAND`, and `ACP_PROMPT_TIMEOUT`; the
  pinned agent ignores all three under `AGENT_KIND: openhands`.
- Remove the log artifact upload, which only matched paths the pinned agent
  never writes.
- Remove the `lmnr-api-key` input and stop setting `LMNR_PROJECT_API_KEY`. The
  action now sends no telemetry. `lmnr-package` remains pinned because the
  pinned agent script imports `lmnr` at module scope. Workflows still passing
  `lmnr-api-key` will see an unexpected-input warning and no other change.
- Document the `use-sub-agents` cost tradeoff, reserved skill filenames, and the
  full input set.
- Add `AGENTS.md` and `CLAUDE.md` with repository conventions and the upstream
  divergence list.
- Skip a review when the pull request carries the configurable `skip-label`.
  The example and this repository's self-review workflow also short-circuit at
  job level so a labelled PR never starts a runner.
- Document `paths-ignore` and its required-status-check caveat in the example.

## 1.0.0 - 2026-07-30

- Add automatic OpenHands PR review with MiniMax M3 defaults.
- Add full-repository and file-level sub-agent inspection.
- Track resolved, still-present, obsolete, and new findings across reruns.
- Load consumer-owned skills and optional plain Markdown best-practices files.
- Pin upstream review code, Python packages, and nested GitHub Actions.
- Provide an advisory, same-repository automatic workflow example.
