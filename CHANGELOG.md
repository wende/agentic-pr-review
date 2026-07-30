# Changelog

## Unreleased

- Add persistent repository review memory backed by a GitHub issue.
- Evaluate memory in a separate post-review model phase and publish only
  validated structured decisions.
- Add a self-review workflow using the repository's memory issue.
- Supply MiniMax prices to telemetry without changing its OpenAI-compatible request path.
- Steer the coordinator to publish after 40 iterations and enforce a hard
  60-iteration ceiling.
- Verify that the current run publishes a new marked review.
- Remove the unused reaction-based review feedback footer.

## 1.0.0 - 2026-07-30

- Add automatic OpenHands PR review with MiniMax M3 defaults.
- Add full-repository and file-level sub-agent inspection.
- Track resolved, still-present, obsolete, and new findings across reruns.
- Load consumer-owned skills and optional plain Markdown best-practices files.
- Pin upstream review code, Python packages, and nested GitHub Actions.
- Provide an advisory, same-repository automatic workflow example.
