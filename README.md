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

No separate GitHub token is required. GitHub Actions supplies a short-lived
`GITHUB_TOKEN` for reading pull requests, publishing reviews, and maintaining
repository memory.

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

### Plain best-practices file

If a repository already has a plain Markdown guide, it does not need skill
frontmatter. Point the action at it:

```yaml
- uses: wende/agentic-pr-review@v1.0.0
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
    review-guidance-path: .github/review-best-practices.md
```

The action validates that the path stays inside the checked-out consumer
repository and wraps the file as a `/codereview` skill for that run.

### Public and specific skills

With `load-public-skills: true`, OpenHands loads its public skill catalog and
activates relevant skills from the review prompt and repository context. Set it
to `false` for a smaller, project-only context.

For deterministic skills, commit the exact skill Markdown files to
`.agents/skills/` in the consumer repository. OpenHands loads those files
directly; no package installation or network fetch is required. Skills using the
`/codereview` trigger are active for every review. Other triggers are activated
when their keywords appear in the review task.

## Configuration

The default model is `openai/MiniMax-M3` at
`https://api.minimax.io/v1`. Override `llm-model` and `llm-base-url` for another
LiteLLM-compatible provider.

The default intentionally uses MiniMax's OpenAI-compatible request path. Before
the reviewer starts, the Action gives OpenHands the native
`minimax/MiniMax-M3` input and output prices for telemetry only. It does not
register or reroute the adapter model in LiteLLM, so request and tool-use
behavior stay unchanged.

Important inputs:

| Input | Default | Purpose |
| --- | --- | --- |
| `llm-model` | `openai/MiniMax-M3` | LiteLLM model identifier |
| `llm-base-url` | MiniMax API | OpenAI-compatible endpoint |
| `use-sub-agents` | `true` | File-level delegation for large reviews |
| `max-review-iterations` | `40` | Turn ceiling for the coordinator and each sub-agent |
| `load-public-skills` | `true` | OpenHands public skill catalog |
| `require-evidence` | `false` | Require end-to-end PR evidence |
| `review-guidance-path` | empty | Plain Markdown review rules from the consumer |
| `memory-enabled` | `true` | Load and update persistent repository memory |
| `memory-issue-number` | empty | Existing memory issue; otherwise discover or create it |
| `enable-uv-cache` | `false` | Shared dependency cache; disabled for security |

The built-in review protocol budgets at most 35 tool actions for investigation
and reserves its final actions for publishing. The Action separately enforces
the iteration ceiling and fails the review step if the agent exits without
posting a marked review for the current commit.

## Persistent repository memory

By default, the action discovers or creates an issue named
`[agentic-pr-review] Repository memory`. The issue body is only a storage marker;
the versioned Action skill is the single source of truth for memory behavior.
Before each review, the action loads up to 100 accepted, marked comments as a
`/codereview` skill. The reviewer never writes memory on the first review. On a
later review, it may append one new comment only when it verifies that feedback
from its previous review was applied in the new code and the resulting lesson
generalizes beyond that one fix into a durable code-quality or design principle.

Memory comments are append-only to avoid lost updates when different pull
requests are reviewed concurrently. The loader ignores unmarked comments and
accepts marked entries only from repository owners, members, collaborators, or
the built-in `github-actions[bot]`. Pull request text and changed files are
never sufficient evidence for a memory update. Still-present findings,
obsolete findings, resolved-thread metadata, and one-off fixes are not stored.
Each accepted entry records the original review concern, how the implementation
fixed it, the generalized lesson, and links or paths supporting that conclusion.

The consumer workflow must grant `issues: write`; the example already does.
For deterministic setup, create the memory issue once and pass its number:

```yaml
- uses: wende/agentic-pr-review@v1.0.0
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
    memory-issue-number: '123'
```

Set `memory-enabled: 'false'` to run without persistent memory.

## Versioning

Pin a complete release such as `wende/agentic-pr-review@v1.0.0` for
reproducibility. Major compatibility tags such as `v1` may move to newer
backward-compatible releases.

The action pins OpenHands extensions, SDK/tools packages, and nested GitHub
Actions. Dependabot proposes dependency upgrades for review and testing before a
release.

## Reviewer identity

With `github.token`, reviews appear from `github-actions[bot]`. Pass a
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
