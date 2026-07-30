#!/usr/bin/env python3
"""Run the pinned review agent with bounded turns and telemetry-only pricing."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import litellm
import openhands.sdk


MODEL_COST_ALIASES = {
    # Reuse the canonical cost fields without registering the adapter model in
    # LiteLLM, which would alter provider/model capability detection.
    "openai/MiniMax-M3": "minimax/MiniMax-M3",
}

def configured_symbols(model: str, max_iterations: int) -> tuple[object, object]:
    canonical_model = MODEL_COST_ALIASES.get(model)
    canonical_info = (
        litellm.model_cost.get(canonical_model)
        if canonical_model is not None
        else None
    )
    if canonical_model is not None and canonical_info is None:
        raise RuntimeError(f"LiteLLM has no pricing metadata for {canonical_model}")

    original_llm = openhands.sdk.LLM
    original_conversation = openhands.sdk.Conversation

    def telemetry_priced_llm(*args: object, **kwargs: object) -> object:
        configured_model = kwargs.get("model")
        if configured_model == model and canonical_info is not None:
            kwargs.setdefault(
                "input_cost_per_token",
                canonical_info["input_cost_per_token"],
            )
            kwargs.setdefault(
                "output_cost_per_token",
                canonical_info["output_cost_per_token"],
            )
        return original_llm(*args, **kwargs)

    def bounded_conversation(*args: object, **kwargs: object) -> object:
        kwargs.setdefault("max_iteration_per_run", max_iterations)
        return original_conversation(*args, **kwargs)

    return telemetry_priced_llm, bounded_conversation


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-agent.py PATH_TO_AGENT_SCRIPT")

    agent_script = Path(sys.argv[1]).resolve()
    if not agent_script.is_file():
        raise SystemExit(f"review agent script not found: {agent_script}")

    try:
        max_iterations = int(os.environ.get("MAX_REVIEW_ITERATIONS", "40"))
    except ValueError as error:
        raise SystemExit("MAX_REVIEW_ITERATIONS must be a positive integer") from error
    if max_iterations < 1:
        raise SystemExit("MAX_REVIEW_ITERATIONS must be a positive integer")

    llm_factory, conversation_factory = configured_symbols(
        os.environ.get("LLM_MODEL", ""),
        max_iterations,
    )
    agent_globals = runpy.run_path(
        str(agent_script),
        run_name="_agentic_pr_review_upstream",
    )
    agent_main = agent_globals["main"]
    agent_main.__globals__["LLM"] = llm_factory
    agent_main.__globals__["Conversation"] = conversation_factory
    agent_main()


if __name__ == "__main__":
    main()
