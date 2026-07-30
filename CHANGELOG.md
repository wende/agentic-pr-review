# Changelog

## Unreleased

- Add persistent repository review memory backed by a GitHub issue.
- Add a self-review workflow using the repository's memory issue.
- Register MiniMax pricing metadata without changing its OpenAI-compatible request path.
- Remove the unused reaction-based review feedback footer.

## 1.0.0 - 2026-07-30

- Add automatic OpenHands PR review with MiniMax M3 defaults.
- Add full-repository and file-level sub-agent inspection.
- Track resolved, still-present, obsolete, and new findings across reruns.
- Load consumer-owned skills and optional plain Markdown best-practices files.
- Pin upstream review code, Python packages, and nested GitHub Actions.
- Provide an advisory, same-repository automatic workflow example.
