# CLAUDE.md

Read [AGENTS.md](AGENTS.md) first — it holds the repository conventions, the
pinning rules, the contract-test rationale, and the release checklist. This file
only adds what is specific to Claude Code.

## Quick orientation

This repository *is* a published GitHub composite action. Nothing is built or
bundled; `action.yml` is the product. There is no package.json and no
dependency install step.

Run the whole test suite:

```bash
node --test test/*.test.mjs
```

## Working here

- The contract suite is fast and has no dependencies. Run it after any edit to
  `action.yml`, `examples/automatic-review.yml`, `skills/follow-up-review.md`,
  or `scripts/install-guidance.sh` — those four files are what it asserts on.
- A failing assertion after a version bump is the suite working as intended, not
  a broken test. Update the assertion in the same commit as the bump.
- Behaviour of the action cannot be exercised locally end to end; it needs a
  live `pull_request` event and a model key. Verify by reading the pinned
  upstream `agent_script.py` rather than by guessing what an env var does.
- `scripts/install-guidance.sh` *can* be run locally, and the test does exactly
  that. Extend that test rather than writing a scratch script.
- Don't add tooling (linters, formatters, package managers) without being asked.
  The zero-dependency setup is deliberate.
