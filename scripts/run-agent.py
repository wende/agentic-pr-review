#!/usr/bin/env python3
"""Run the pinned review agent with cost metadata for adapter-backed models."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import litellm


MODEL_COST_ALIASES = {
    # Keep the generic OpenAI-compatible request path while reusing LiteLLM's
    # native MiniMax pricing entry for telemetry.
    "openai/MiniMax-M3": "minimax/MiniMax-M3",
}

COST_FIELDS = {
    "cache_creation_input_token_cost",
    "cache_read_input_token_cost",
    "cache_read_input_token_cost_above_512k_tokens",
    "input_cost_per_token",
    "input_cost_per_token_above_512k_tokens",
    "output_cost_per_token",
    "output_cost_per_token_above_512k_tokens",
}


def register_cost_alias(model: str) -> None:
    canonical_model = MODEL_COST_ALIASES.get(model)
    if canonical_model is None:
        return

    canonical_info = litellm.model_cost.get(canonical_model)
    if canonical_info is None:
        raise RuntimeError(
            f"LiteLLM has no pricing metadata for {canonical_model}"
        )

    model_info = {
        field: canonical_info[field]
        for field in COST_FIELDS
        if field in canonical_info
    }
    model_info.setdefault("cache_creation_input_token_cost", 0)
    model_info["litellm_provider"] = model.split("/", 1)[0]
    model_info["mode"] = "chat"
    litellm.register_model(model_cost={model: model_info})


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-agent.py PATH_TO_AGENT_SCRIPT")

    agent_script = Path(sys.argv[1]).resolve()
    if not agent_script.is_file():
        raise SystemExit(f"review agent script not found: {agent_script}")

    register_cost_alias(os.environ.get("LLM_MODEL", ""))
    runpy.run_path(str(agent_script), run_name="__main__")


if __name__ == "__main__":
    main()
