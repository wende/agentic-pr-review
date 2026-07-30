# Agentic PR Review

Versioned, automatic pull request review powered by OpenHands and any
OpenAI-compatible model endpoint.

The reviewer receives the complete PR manifest and patches, checks out the full
repository, can inspect files and run read-only commands, reads previous reviews
and threads, and can delegate large diffs to file-level sub-agents.

On every rerun it identifies its latest completed review, verifies earlier
findings against the current HEAD, summarizes what was resolved or remains, and
adds inline comments only for new or materially changed findings.

## Install

Copy [`examples/automatic-review.yml`](examples/automatic-review.yml) to
`.github/workflows/agentic-pr-review.yml` in the consumer repository.

Add an Actions secret named `MINIMAX_API_KEY`. For multiple repositories,
prefer an organization-level secret restricted to the intended repositories.

The example automatically reviews:

- newly opened and reopened PRs;
- draft PRs and every new commit;
- the transition from draft to ready for review.

It skips fork PRs because the safe `pull_request` event does not expose
repository secrets to forked code. Reviews are advisory and cannot block a PR
when a model provider or third-party service is unavailable.

## Project-specific guidance

Add optional review rules to the consumer repository:

```text
.agents/skills/project-code-review.md
```

Use a unique skill name and the `/codereview` trigger:

```markdown
---
name: project-code-review
description: Project-specific correctness guidance
triggers:
  - /codereview
---

# Project review guidance

- Check protocol compatibility between the client and server.
- Trace cancellation, timeout, and cleanup paths.
```

The action injects its versioned follow-up protocol alongside these local
project rules.

## Configuration

The default model is `openai/MiniMax-M3` at
`https://api.minimax.io/v1`. Override `llm-model` and `llm-base-url` for another
LiteLLM-compatible provider.

Important inputs:

| Input | Default | Purpose |
| --- | --- | --- |
| `llm-model` | `openai/MiniMax-M3` | LiteLLM model identifier |
| `llm-base-url` | MiniMax API | OpenAI-compatible endpoint |
| `use-sub-agents` | `true` | File-level delegation for large reviews |
| `load-public-skills` | `true` | OpenHands public skill catalog |
| `collect-feedback` | `true` | Reaction controls in review bodies |
| `require-evidence` | `false` | Require end-to-end PR evidence |
| `enable-uv-cache` | `false` | Shared dependency cache; disabled for security |

## Versioning

Pin a complete release such as `wende/agentic-pr-review@v1.0.0` for
reproducibility. Major compatibility tags such as `v1` may move to newer
backward-compatible releases.

The action pins OpenHands extensions, SDK/tools packages, and nested GitHub
Actions. Dependabot proposes dependency upgrades for review and testing before a
release.

## Reviewer identity

With `secrets.GITHUB_TOKEN`, reviews appear from `github-actions[bot]`. Pass a
GitHub App installation token as `github-token` to use a dedicated reviewer name
and avatar.

## Security

- Uses `pull_request`, not `pull_request_target`.
- Skips forks by default in the consumer workflow.
- Does not persist checkout credentials.
- Disables shared dependency caching by default.
- Pins executable dependencies.
- Grants the GitHub token only repository-read and PR-comment permissions in the
  consumer workflow.

PR content is untrusted input to an agent with terminal and file tools. Keep
this action advisory, use GitHub-hosted or isolated runners, and do not provide
unrelated secrets to the review job.
