# AGENTS.md

Working conventions for coding agents in this repository. Human contributors
should follow them too.

## What this repository is

A published GitHub composite action (`wende/agentic-pr-review`) that runs an
OpenHands-based reviewer against a pull request. There is no application code
here and nothing is built or bundled: the repository *is* the action.

```
action.yml                  the action itself — inputs, pinned versions, steps
skills/follow-up-review.md  versioned review protocol injected into consumers
scripts/install-guidance.sh installs skills into the consumer checkout
scripts/dedupe-reviews.sh   collapses duplicate reviews the agent published
examples/automatic-review.yml  the workflow consumers copy
test/contract.test.mjs      contract tests over all of the above
.github/workflows/ci.yml    node --test, git diff --check, actionlint
```

## Constraints that matter

**Everything executable is pinned.** Nested actions by commit SHA with a `# vX`
comment, `OpenHands/extensions` by commit, Python packages by exact version.
Never relax a pin to a tag or range.

**`extensions-version` and the package pins move together.** The
`openhands-sdk` and `openhands-tools` versions must match each other and be
compatible with the pinned extensions commit. Bumping one alone is a bug.
Verify against the upstream script before bumping:
`https://github.com/OpenHands/extensions/blob/<sha>/plugins/pr-review/scripts/agent_script.py`

**The env contract with upstream is implicit.** `action.yml` passes environment
variables that `agent_script.py` reads by name. Nothing validates the pairing,
so an upstream rename silently disables a feature, and a stale variable looks
like live configuration while doing nothing. When touching either side, grep
the upstream script for the variable. The contract suite asserts that known-dead
variables stay absent.

## Relationship to upstream

`action.yml` is a derivative of upstream's
`plugins/pr-review/action.yml`. Diff against it whenever you bump
`extensions-version`:

```bash
git clone --filter=blob:none --no-checkout https://github.com/OpenHands/extensions
git -C extensions sparse-checkout set --no-cone /plugins/pr-review
git -C extensions checkout <extensions-version>
```

Deliberate divergences to preserve — do not "fix" them back:

- **Narrower surface.** We hardcode `AGENT_KIND: openhands` and expose no ACP
  inputs, no `agent-kind`, and no `review-style` (deprecated upstream).
- **Stricter pinning.** Upstream installs `openhands-tools` and `lmnr`
  unpinned; we pin both, plus nested actions by SHA.
- **`persist-credentials: false` on both checkouts.** Upstream sets it only on
  the PR checkout.
- **`use-sub-agents` defaults to `true`.** Upstream defaults to `false` for cost
  and timeout reasons (extensions#208). Documented in the README; revisit if
  timeouts appear.
- **Cost is reported, not just printed.** Upstream's `log_cost_summary` writes
  to stdout on its success path only. `run-agent.py` reads the same numbers off
  `conversation.conversation_stats` in a `finally` and writes the job summary
  and the action outputs, so a failed review still accounts for its spend.
  Never replace that with parsing upstream's log text.
- **No Laminar telemetry.** Upstream exposes `lmnr-api-key` and uploads a trace
  artifact; we plumb no key, so the export is inert. `lmnr-package` stays pinned
  only because `agent_script.py` imports `lmnr` at module scope — dropping the
  install raises `ImportError` before the review runs. Re-check that import on
  every `extensions-version` bump; if it becomes optional, drop the input.

Known upstream features not forwarded: comma-separated `llm-model` A/B testing
(upstream resolves it in a `select-model` step; we pass the input straight
through).

**Security posture is a feature, not an accident.** The action uses
`pull_request` (never `pull_request_target`), sets `persist-credentials: false`
on both checkouts, keeps the uv cache off by default, and passes PR title and
body as env vars rather than shell interpolation. Any change that weakens one of
these needs an explicit threat-model note in the PR and in
[SECURITY.md](SECURITY.md).

**The size gate must cover every step after the early gates.** `Evaluate skip
label` runs first, then `Check pull request size`. Every later step carries
both `steps.skip.outputs.skip != 'true'` and (except the size report step)
`steps.size.outputs.oversized != 'true'`. Composite actions cannot return
early, so a step added without the guards silently runs on pull requests the
gates were meant to skip. The contract suite asserts the size-guard count
equals step count minus three; add both guards when you add a step.

**`install-guidance.sh` handles attacker-influenced paths.** It rejects absolute
paths, `..` segments, and symlinks resolving outside the checkout. Changes there
need a matching test case.

## Tests

```bash
node --test test/*.test.mjs
```

No dependencies, no package.json, Node's built-in test runner only. Keep it that
way — the suite must run on a clean checkout with nothing installed.

These are contract tests, not unit tests: they assert that
security-relevant strings and pinned versions are present in `action.yml`, the
example workflow, and the follow-up skill. That is deliberate. A version bump is
*supposed* to fail CI until the assertion is updated in the same commit, which
is what forces the bump to be reviewed.

When you add an input, a pin, or a security flag, add the corresponding
assertion. When you change the follow-up protocol's vocabulary (`resolved`,
`still present`, `obsolete`) or its marker, update
[`test/contract.test.mjs`](test/contract.test.mjs) in the same change.

Prefer extending the contract suite over writing throwaway scripts.

## Changing the review protocol

[`skills/follow-up-review.md`](skills/follow-up-review.md) is a released
artifact — consumers pinned to a tag get exactly that file. Two things in it are
compatibility surface:

- the `<!-- agentic-pr-review -->` marker, and the legacy
  `<!-- macbeth-openhands-review -->` marker kept for migration;
- the `<!-- agentic-pr-review-superseded -->` marker `dedupe-reviews.sh` writes
  over collapsed duplicates, which must never start with the review marker;
- the `resolved` / `still present` / `obsolete` classification vocabulary.

Changing either breaks follow-up tracking on in-flight PRs. Do not drop the
legacy marker without a major version bump.

## Release checklist

1. Update `action.yml` pins.
2. Update the matching assertions in `test/contract.test.mjs`.
3. Update the version in `examples/automatic-review.yml` and its assertion.
4. Update the input tables in [README.md](README.md) if inputs changed.
5. Add a [CHANGELOG.md](CHANGELOG.md) entry.
6. Tag `vX.Y.Z`, then move the `vX` major tag.

## Style

- Markdown wraps at roughly 80 columns; the existing files do.
- Prose is declarative and terse. No marketing voice, no emoji.
- Bash scripts: `#!/usr/bin/env bash` plus `set -euo pipefail`, quote every
  expansion.
- Commit messages are plain imperative summaries with no AI attribution.
- Never push or tag without being asked.
