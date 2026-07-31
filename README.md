# Agentic PR Review

Versioned, automatic pull request review powered by [OpenHands](https://github.com/OpenHands/extensions)
and any OpenAI-compatible model endpoint.

The reviewer receives the complete PR manifest and patches, checks out the full
repository, can inspect files and run read-only commands, reads previous reviews
and threads, and can delegate large diffs to file-level sub-agents.

On every rerun it identifies its latest completed review, verifies earlier
findings against the current HEAD, summarizes what was resolved or remains, and
adds inline comments only for new or materially changed findings. Settled work
is counted rather than restated: resolved findings and findings the author
declined in a thread reply are not narrated again on later runs.

## What the action does

The action is a composite action. Each run, in order:

1. Measures the PR against `max-changed-lines`. Above the limit it comments and
   stops; every later step is skipped.
2. Checks out `OpenHands/extensions` at the pinned `extensions-version` commit.
3. Checks out the PR head repository at full depth, with submodules and without
   persisting credentials.
4. Installs the versioned follow-up protocol — and, optionally, the consumer's
   own guidance file — into `.agents/skills/` of that checkout
   ([`scripts/install-guidance.sh`](scripts/install-guidance.sh)).
5. Sets up Python 3.12 and [uv](https://github.com/astral-sh/uv).
6. Validates that `llm-api-key`, `github-token`, `llm-model`, and a
   `pull_request` event context are all present.
7. Verifies the token can actually submit reviews by creating and immediately
   deleting a pending review — so a permissions problem fails fast rather than
   after a full model run.
8. Runs the pinned OpenHands PR-review agent script.
9. Collapses any duplicate review the agent published for the same commit
   ([`scripts/dedupe-reviews.sh`](scripts/dedupe-reviews.sh)).

10. Writes the run's cost, token counts, and iteration count to the job summary
    and to the action's outputs.

Agent progress goes to the job log; the action uploads no artifacts.

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
repository secrets to forked code. Reviews are advisory (`continue-on-error:
true`) and cannot block a PR when a model provider or third-party service is
unavailable.

## Configuration

The default model is `openai/MiniMax-M3` at `https://api.minimax.io/v1`.
Override `llm-model` and `llm-base-url` for any other LiteLLM-compatible
provider.

### Required inputs

| Input | Purpose |
| --- | --- |
| `llm-api-key` | Model API key |
| `github-token` | Token used to read PR context and submit reviews |

### Review behaviour

| Input | Default | Purpose |
| --- | --- | --- |
| `llm-model` | `openai/MiniMax-M3` | LiteLLM model identifier (single model; comma-separated A/B lists are not supported) |
| `llm-base-url` | `https://api.minimax.io/v1` | OpenAI-compatible endpoint |
| `use-sub-agents` | `true` | File-level delegation for large reviews — see the cost note below |
| `review-wrap-up-iterations` | `40` | Stop investigation and steer the coordinator to publication |
| `review-wrap-up-seconds` | `1200` | Same, whichever trips first — bounds wall time when turns are slow |
| `subagent-wrap-up-iterations` | `25` | Stop investigation and steer a delegated review to reporting its findings |
| `subagent-wrap-up-seconds` | `600` | Same for delegated reviews, whichever trips first |
| `max-review-iterations` | `60` | Hard turn ceiling for the coordinator and each sub-agent |
| `load-public-skills` | `true` | Load the OpenHands public skill catalog |
| `require-evidence` | `false` | Require end-to-end evidence in the PR description |
| `review-guidance-path` | empty | Plain Markdown review rules from the consumer repository |
| `memory-enabled` | `true` | Load and update persistent repository memory |
| `memory-issue-number` | empty | Existing memory issue; otherwise discover or create it |
| `max-changed-lines` | `10000` | Skip and comment above this many changed lines; `0` disables |
| `skip-label` | `skip-review` | Label that skips the review; empty disables it |

### Pinning and infrastructure

| Input | Default | Purpose |
| --- | --- | --- |
| `extensions-version` | `9def413…baea45` | Pinned `OpenHands/extensions` commit |
| `openhands-sdk-package` | `openhands-sdk==1.39.0` | Pinned SDK package spec |
| `openhands-tools-package` | `openhands-tools==1.39.0` | Pinned tools package spec |
| `lmnr-package` | `lmnr==0.7.57` | Pinned Laminar client spec; required by an upstream import, no telemetry sent |
| `enable-uv-cache` | `false` | Shared dependency cache; disabled for security |

The SDK and tools package versions must be kept in step with each other and with
`extensions-version`; [`test/contract.test.mjs`](test/contract.test.mjs) asserts
the pinned values so an unreviewed bump fails CI.

### Outputs

Every completed review writes a usage table to the GitHub Actions job summary,
so spend is visible on the run page without opening the log:

| Metric | Value |
| --- | --- |
| Model | `openai/MiniMax-M3` |
| Cost | $0.8712 |
| Input tokens | 412,908 |
| Output tokens | 18,442 |
| Coordinator iterations | 34 / 60 |

The same numbers are exposed as action outputs, so a job can gate on them:

| Output | Purpose |
| --- | --- |
| `cost` | Accumulated cost in USD, including delegated sub-agents |
| `input-tokens` | Prompt tokens consumed |
| `output-tokens` | Completion tokens produced |
| `iterations` | Coordinator iterations completed |

```yaml
- id: review
  uses: wende/agentic-pr-review@v1
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
- name: Enforce a per-review budget
  run: |
    if (( $(echo "${{ steps.review.outputs.cost }} > 2.0" | bc -l) )); then
      echo "::warning::This review cost ${{ steps.review.outputs.cost }}"
    fi
```

The values come from the SDK conversation the review ran in, not from parsing
log text. Iterations are reported against `max-review-iterations`, so a review
truncated by the ceiling is visible as such rather than looking complete. A
review that fails partway still reports what it spent before failing; cost
reads as unavailable when LiteLLM carries no pricing metadata for the model.
Repository memory evaluation runs after the review and is not counted.

The review itself is still consumed as the review GitHub posts on the PR.

### Oversized pull requests

Above `max-changed-lines` (additions plus deletions, default `10000`), the
action posts a comment and skips the review entirely. The check is one API call
and runs before the checkouts, so an oversized PR costs no clone and no model
call.

The comment is edited in place on later pushes rather than reposted, so a
long-running large PR accumulates one notice, not one per commit. When the PR
later drops under the limit, that notice is deleted before the review runs.

Reviews at that size are the ones least worth paying for: the diff exceeds what
the reviewer can hold in useful context, so findings get shallow while cost
grows. Split the PR, or raise the limit for a repository where large mechanical
diffs are normal:

```yaml
with:
  max-changed-lines: '25000'   # or '0' to review any size
```

### Sub-agent cost

`use-sub-agents` defaults to `true` here, which diverges from upstream
OpenHands: they default it to `false` because file-level delegation carries
high token cost and can push long reviews past the job timeout
([extensions#208](https://github.com/OpenHands/extensions/issues/208)).

The default favours review depth on large diffs. If reviews are timing out
against the example workflow's 35-minute cap, or model spend is higher than
expected, set `use-sub-agents: 'false'` first — it is the largest single cost
lever in this action. The job summary reports what each run actually spent, so
the change can be measured rather than guessed at; see [Outputs](#outputs).

## Skipping reviews

### By path

Uncomment `paths-ignore` in the example workflow to stop reviewing pull
requests that touch only documentation or other uninteresting files:

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize]
    paths-ignore:
      - '**/*.md'
      - 'docs/**'
```

The filter is all-or-nothing: a pull request touching one source file and
twenty Markdown files still runs, which is the intended behaviour.

A workflow filtered out this way reports no status at all, so do not combine
`paths-ignore` with a required status check. The review is advisory today
(`continue-on-error: true`), so this is safe as shipped.

### By label

Add the `skip-review` label to opt a single pull request out — a revert, a
mechanical rename, a release commit. Both the published example and this
repository's self-review workflow check the label at job level, so a labelled
pull request never starts a runner.

Rename the label with `skip-label`, or set it to an empty value to disable the
check:

```yaml
- uses: wende/agentic-pr-review@v1.1.0
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
    skip-label: no-ai-review
```

The action enforces `skip-label` itself, so a custom name works with any
workflow. Consumers using the example (or a workflow that copies its job-level
`if:`) should also update the hard-coded label in that expression, which keeps
the cheap never-start-a-runner path.

The label is read from the event payload, so labelling an in-flight review does
not cancel it. The next push cancels it anyway through the existing
`cancel-in-progress` concurrency group.

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

The action injects its versioned follow-up protocol
([`skills/follow-up-review.md`](skills/follow-up-review.md)) alongside these
local project rules.

### Plain best-practices file

If a repository already has a plain Markdown guide, it does not need skill
frontmatter. Point the action at it:

```yaml
- uses: wende/agentic-pr-review@v1.1.0
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
    review-guidance-path: .github/review-best-practices.md
```

The path must be repository-relative; absolute paths, `..` segments, and
symlinks that resolve outside the checkout are rejected. The file is normalized
(CRLF stripped) and wrapped as a `/codereview` skill named
`repository-review-best-practices` for that run.

Reserved skill filenames the action writes into the checkout — do not commit
your own files under these names:

- `.agents/skills/agentic-review-follow-up.md`
- `.agents/skills/repository-review-best-practices.md`
- `.agents/skills/agentic-review-repository-memory.md`

### Public and specific skills

With `load-public-skills: true`, OpenHands loads its public skill catalog and
activates relevant skills from the review prompt and repository context. Set it
to `false` for a smaller, project-only context.

For deterministic skills, commit the exact skill Markdown files to
`.agents/skills/` in the consumer repository. OpenHands loads those files
directly; no package installation or network fetch is required. Skills using the
`/codereview` trigger are active for every review. Other triggers are activated
when their keywords appear in the review task.

## Reviewer identity

With `secrets.GITHUB_TOKEN`, reviews appear from `github-actions[bot]`. Pass a
GitHub App installation token as `github-token` to use a dedicated reviewer name
and avatar.

The default intentionally uses MiniMax's OpenAI-compatible request path. Before
the reviewer starts, the Action gives OpenHands the native
`minimax/MiniMax-M3` input and output prices for telemetry only. It does not
register or reroute the adapter model in LiteLLM, so request and tool-use
behavior stay unchanged.

The follow-up protocol keys off a hidden marker at the top of every review body:

```html
<!-- agentic-pr-review -->
```

Reviews starting with the legacy `<!-- macbeth-openhands-review -->` marker are
also recognized as checkpoints, so existing PRs keep their history across the
rename.

The agent publishes its own review, and GitHub answers a review POST without a
`comments` array — a model that reads that zero count as a rejection re-posts
the whole body once per inline comment. After publication the action keeps the
newest marked review for the current commit and rewrites the body of every
other one to:

```html
<!-- agentic-pr-review-superseded -->
```

Collapsed reviews no longer carry the review marker, so a later run does not
mistake one for its checkpoint. Duplicate inline comments from those reviews are
deleted, except any comment carrying a reply — an answered thread is never
removed. A rerun on an unchanged commit collapses the previous run's review too,
so a commit carries one readable review body rather than one per run.

With the defaults, after 40 coordinator iterations *or* 1200 seconds of
coordinator working time — whichever comes first — the runtime injects an
environment message that forbids further investigation and directs the agent
to publish using its existing evidence. The remaining 20 iterations are a
wrap-up grace period. The hard 60-iteration ceiling still bounds cost, and the
Action fails the review step if the agent exits without posting a new marked
review.

Delegated file reviews get the same treatment on their own budgets (25
iterations or 600 seconds), directing them to return partial findings to the
coordinator rather than nothing. Both bounds matter because per-turn latency
grows with context size: a fixed iteration budget can span wildly different
wall-clock durations, so the time budget is what actually caps how long a
review takes.

## Telemetry

This action sends no telemetry. Upstream OpenHands supports
[Laminar](https://www.lmnr.ai/) tracing; this action deliberately plumbs no key
through, so the agent's trace export is inert and it writes no trace file.

The `lmnr` package is still installed and pinned only because the pinned agent
script imports it at module scope — removing it breaks the review before it
starts. If that import ever becomes optional upstream, drop `lmnr-package` too.

Review progress goes to the GitHub Actions job log, and the per-run cost and
token summary to the job summary and the action's outputs — see
[Outputs](#outputs). Neither leaves GitHub.

## Persistent repository memory

By default, the action discovers or creates an issue named
`[agentic-pr-review] Repository memory`. The issue body is only a storage marker;
the versioned Action files are the source of truth for memory behavior.
Before each review, the action loads up to 100 accepted, marked comments as a
`/codereview` skill. The main reviewer only consumes memory; it cannot update
the issue. After a marked review is published, a separate focused model call
compares inline comments from the immediately previous marked review with the
changes made since that checkpoint. It must produce a structured candidate or
an explicit no-candidate decision.

A deterministic publication step validates that a candidate references an
inline comment belonging to the previous marked review and that its evidence
paths changed since that review. It then appends at most one memory comment.
Missing or malformed decisions fail visibly instead of silently skipping
memory. This adds exactly one focused model call when a follow-up has inline
comments to evaluate. First reviews and follow-ups without previous inline
comments need no model call; no-candidate decisions leave the issue unchanged.

Memory comments are append-only to avoid lost updates when different pull
requests are reviewed concurrently. The loader ignores unmarked comments and
accepts marked entries only from repository owners, members, collaborators, or
the built-in `github-actions[bot]`. Pull request text and changed files are
never sufficient evidence for a memory update. Still-present findings,
obsolete findings, resolved-thread metadata, and one-off fixes are not stored.
Each accepted entry records the original review concern, how the implementation
fixed it, the generalized lesson, and links or paths supporting that conclusion.
Entries are idempotent by source review-comment ID.

The consumer workflow must grant `issues: write`; the example already does.
For deterministic setup, create the memory issue once and pass its number:

```yaml
- uses: wende/agentic-pr-review@v1.1.0
  with:
    llm-api-key: ${{ secrets.MINIMAX_API_KEY }}
    github-token: ${{ github.token }}
    memory-issue-number: '123'
```

Set `memory-enabled: 'false'` to run without persistent memory.

## Versioning

Pin a complete release such as `wende/agentic-pr-review@v1.1.0` for
reproducibility. Major compatibility tags such as `v1` may move to newer
backward-compatible releases.

The action pins OpenHands extensions, SDK/tools packages, and nested GitHub
Actions by commit SHA. Dependabot proposes GitHub Actions upgrades weekly for
review and testing before a release. Python package pins are updated by hand
alongside `extensions-version`.

## Security

- Uses `pull_request`, not `pull_request_target`.
- Skips forks by default in the consumer workflow.
- Does not persist checkout credentials for either checkout.
- Disables shared dependency caching by default.
- Pins executable dependencies by commit SHA or exact version.
- Passes PR title and body as environment variables, never interpolated into
  shell scripts.
- The consumer workflow grants only `contents: read` plus `pull-requests: write`
  and `issues: write`, which are the minimum for submitting reviews and
  maintaining repository memory.

PR content is untrusted input to an agent with terminal and file tools. Keep
this action advisory, use GitHub-hosted or isolated runners, and do not provide
unrelated secrets to the review job. See [SECURITY.md](SECURITY.md) for
reporting.

## Development

```bash
node --test test/*.test.mjs
```

[`test/contract.test.mjs`](test/contract.test.mjs) is a contract suite: it
asserts the pinned versions, the security-relevant flags in
[`action.yml`](action.yml), the follow-up protocol's marker and vocabulary, the
guidance installer's path-escape rejection, and the example workflow's fork
guard. CI additionally runs `git diff --check` and
[actionlint](https://github.com/rhysd/actionlint).

Working conventions for this repository live in [AGENTS.md](AGENTS.md).
