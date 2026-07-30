#!/usr/bin/env python3
"""Run the pinned review agent with wrap-up steering and bounded turns."""

from __future__ import annotations

import os
import runpy
import sys
import time
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

SUBAGENT_WRAP_UP_MESSAGE = """\
Your investigation budget is exhausted. Stop investigating now. Do not read
more files, search, or run further commands. Using only the evidence already
gathered, immediately return your structured findings to the coordinator.
Report partial findings rather than nothing; omitting what you already found
is worse than reporting it without further verification."""


def steer_agent_to_wrap_up(
    agent: object,
    wrap_up_iterations: int,
    wrap_up_seconds: float,
    message: str,
    label: str,
) -> None:
    original_step = agent.step
    completed_steps = 0
    wrap_up_sent = False
    started_at: float | None = None

    def steered_step(
        _agent: object,
        conversation: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal completed_steps, wrap_up_sent, started_at
        # Start the clock on the first step so the budget covers agent work
        # rather than dependency installation and repository checkout.
        if started_at is None:
            started_at = time.monotonic()
        elapsed = time.monotonic() - started_at

        # Iteration count is a poor proxy for wall time: per-turn latency grows
        # with context size, so a fixed iteration budget can span wildly
        # different durations. Whichever bound trips first ends investigation.
        if not wrap_up_sent and (
            completed_steps >= wrap_up_iterations or elapsed >= wrap_up_seconds
        ):
            reason = (
                f"{completed_steps} completed iterations"
                if completed_steps >= wrap_up_iterations
                else f"{elapsed:.0f}s elapsed"
            )
            # The SDK run loop holds the conversation-state lock while calling
            # agent.step(). Mirror its stop-hook feedback path by appending the
            # environment message directly instead of calling send_message().
            conversation._on_event(
                openhands.sdk.MessageEvent(
                    source="environment",
                    llm_message=openhands.sdk.Message(
                        role="user",
                        content=[
                            openhands.sdk.TextContent(text=message),
                        ],
                    ),
                )
            )
            wrap_up_sent = True
            print(f"Injected {label} wrap-up instruction after {reason}")
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
    wrap_up_seconds: float,
    message: str,
    label: str,
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
                wrap_up_seconds,
                message,
                label,
            )
            steering_installed = True
        return result

    object.__setattr__(
        conversation,
        "_ensure_agent_ready",
        MethodType(ensure_agent_ready_then_steer, conversation),
    )


def steer_subagents_to_wrap_up(
    wrap_up_iterations: int,
    wrap_up_seconds: float,
) -> None:
    """Bound delegated file reviews the same way the coordinator is bounded.

    Rebinding ``Conversation`` in the agent script's globals only reaches the
    conversation that script constructs. Sub-agents are built inside the SDK by
    ``TaskManager``, which imports ``LocalConversation`` directly, so they
    inherit the coordinator's hard iteration cap but never receive a wrap-up
    signal. Patch the factory itself so every delegated review is steered too.
    """
    try:
        from openhands.tools.task.manager import TaskManager
    except ImportError:
        # Delegation is optional; without the task tools there is nothing to
        # steer and the coordinator's own budget already bounds the review.
        return

    original_get_conversation = TaskManager._get_conversation

    def get_conversation_then_steer(
        self: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        conversation = original_get_conversation(self, *args, **kwargs)
        steer_conversation_to_wrap_up(
            conversation,
            wrap_up_iterations,
            wrap_up_seconds,
            SUBAGENT_WRAP_UP_MESSAGE,
            "sub-agent review",
        )
        return conversation

    TaskManager._get_conversation = get_conversation_then_steer


def configured_symbols(
    model: str,
    wrap_up_iterations: int,
    wrap_up_seconds: float,
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
            wrap_up_seconds,
            WRAP_UP_MESSAGE,
            "review",
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
        subagent_wrap_up_iterations = int(
            os.environ.get("SUBAGENT_WRAP_UP_ITERATIONS", "25")
        )
    except ValueError as error:
        raise SystemExit(
            "Review iteration limits must be positive integers"
        ) from error
    if (
        wrap_up_iterations < 1
        or max_iterations < 1
        or subagent_wrap_up_iterations < 1
    ):
        raise SystemExit("Review iteration limits must be positive integers")
    if wrap_up_iterations >= max_iterations:
        raise SystemExit(
            "REVIEW_WRAP_UP_ITERATIONS must be less than MAX_REVIEW_ITERATIONS"
        )

    try:
        wrap_up_seconds = float(
            os.environ.get("REVIEW_WRAP_UP_SECONDS", "1200")
        )
        subagent_wrap_up_seconds = float(
            os.environ.get("SUBAGENT_WRAP_UP_SECONDS", "600")
        )
    except ValueError as error:
        raise SystemExit(
            "Review time budgets must be positive numbers"
        ) from error
    if wrap_up_seconds <= 0 or subagent_wrap_up_seconds <= 0:
        raise SystemExit("Review time budgets must be positive numbers")
    if subagent_wrap_up_seconds >= wrap_up_seconds:
        raise SystemExit(
            "SUBAGENT_WRAP_UP_SECONDS must be less than REVIEW_WRAP_UP_SECONDS"
        )

    llm_factory, conversation_factory = configured_symbols(
        os.environ.get("LLM_MODEL", ""),
        wrap_up_iterations,
        wrap_up_seconds,
        max_iterations,
    )
    steer_subagents_to_wrap_up(
        subagent_wrap_up_iterations,
        subagent_wrap_up_seconds,
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
