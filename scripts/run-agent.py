#!/usr/bin/env python3
"""Run the pinned review agent with wrap-up steering and bounded turns."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path
from types import MethodType

import litellm
import openhands.sdk


MODEL_COST_ALIASES = {
    # Reuse the canonical cost fields without registering the adapter model in
    # LiteLLM, which would alter provider/model capability detection.
    "openai/MiniMax-M3": "minimax/MiniMax-M3",
}

WRAP_UP_MESSAGE = """\
The normal review investigation budget is exhausted. Stop investigating now.
Do not read more files, search, inspect dependencies, run tests, or delegate.
Using only the evidence already gathered, immediately compose and submit the
marked GitHub review. You may use tools only to create and post that review.
If there are no actionable findings, post a concise marked COMMENT review
stating that. The review is incomplete until it is published."""


def steer_agent_to_wrap_up(agent: object, wrap_up_iterations: int) -> None:
    original_step = agent.step
    completed_steps = 0
    wrap_up_sent = False

    def steered_step(
        _agent: object,
        conversation: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal completed_steps, wrap_up_sent
        if completed_steps >= wrap_up_iterations and not wrap_up_sent:
            # The SDK run loop holds the conversation-state lock while calling
            # agent.step(). Mirror its stop-hook feedback path by appending the
            # environment message directly instead of calling send_message().
            conversation._on_event(
                openhands.sdk.MessageEvent(
                    source="environment",
                    llm_message=openhands.sdk.Message(
                        role="user",
                        content=[
                            openhands.sdk.TextContent(text=WRAP_UP_MESSAGE),
                        ],
                    ),
                )
            )
            wrap_up_sent = True
            print(
                "Injected review wrap-up instruction after "
                f"{completed_steps} completed iterations"
            )
        result = original_step(conversation, *args, **kwargs)
        completed_steps += 1
        return result

    object.__setattr__(
        agent,
        "step",
        MethodType(steered_step, agent),
    )


def steer_conversation_to_wrap_up(
    conversation: object,
    wrap_up_iterations: int,
) -> None:
    # Plugin loading creates a Pydantic copy of the agent, so installing the
    # step wrapper before the SDK's lazy initialization would bind it to an
    # abandoned, uninitialized object. Attach it immediately after that
    # lifecycle phase instead.
    original_ensure_agent_ready = conversation._ensure_agent_ready
    steering_installed = False

    def ensure_agent_ready_then_steer(
        _conversation: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal steering_installed
        result = original_ensure_agent_ready(*args, **kwargs)
        if not steering_installed:
            steer_agent_to_wrap_up(
                _conversation.agent,
                wrap_up_iterations,
            )
            steering_installed = True
        return result

    object.__setattr__(
        conversation,
        "_ensure_agent_ready",
        MethodType(ensure_agent_ready_then_steer, conversation),
    )


def configured_symbols(
    model: str,
    wrap_up_iterations: int,
    max_iterations: int,
) -> tuple[object, object]:
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
        kwargs["max_iteration_per_run"] = max_iterations
        conversation = original_conversation(*args, **kwargs)
        steer_conversation_to_wrap_up(
            conversation,
            wrap_up_iterations,
        )
        return conversation

    return telemetry_priced_llm, bounded_conversation


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-agent.py PATH_TO_AGENT_SCRIPT")

    agent_script = Path(sys.argv[1]).resolve()
    if not agent_script.is_file():
        raise SystemExit(f"review agent script not found: {agent_script}")

    try:
        wrap_up_iterations = int(
            os.environ.get("REVIEW_WRAP_UP_ITERATIONS", "40")
        )
        max_iterations = int(os.environ.get("MAX_REVIEW_ITERATIONS", "60"))
    except ValueError as error:
        raise SystemExit(
            "Review iteration limits must be positive integers"
        ) from error
    if wrap_up_iterations < 1 or max_iterations < 1:
        raise SystemExit("Review iteration limits must be positive integers")
    if wrap_up_iterations >= max_iterations:
        raise SystemExit(
            "REVIEW_WRAP_UP_ITERATIONS must be less than MAX_REVIEW_ITERATIONS"
        )

    llm_factory, conversation_factory = configured_symbols(
        os.environ.get("LLM_MODEL", ""),
        wrap_up_iterations,
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
