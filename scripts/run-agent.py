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
stating that. The review is incomplete until it is published. Post it exactly
once: the response to that call carries no comments array, so a zero comment
count in it is not a failure. As soon as the call returns a review ID you are
finished; do not re-post the same body."""

SUBAGENT_WRAP_UP_MESSAGE = """\
Your investigation budget is exhausted. Stop investigating now. Do not read
more files, search, or run further commands. Using only the evidence already
gathered, immediately return your structured findings to the coordinator.
Report partial findings rather than nothing; omitting what you already found
is worse than reporting it without further verification."""

SUMMARY_HEADING = "### Agentic PR review usage"


class ReviewUsage:
    """What the review actually consumed, gathered for the job summary.

    The numbers are read back off the SDK conversation rather than scraped from
    the agent's stdout: upstream's printed cost summary is log formatting with
    no contract behind it, and it is not printed at all when a review fails
    partway through — which is exactly when spend is worth knowing.
    """

    def __init__(self) -> None:
        self.conversations: list[object] = []
        self.iterations = 0


def steer_agent_to_wrap_up(
    agent: object,
    wrap_up_iterations: int,
    wrap_up_seconds: float,
    message: str,
    label: str,
    usage: ReviewUsage | None = None,
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
        if usage is not None:
            usage.iterations = completed_steps
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
    usage: ReviewUsage | None = None,
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
                usage,
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
    usage: ReviewUsage,
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
        usage.conversations.append(conversation)
        steer_conversation_to_wrap_up(
            conversation,
            wrap_up_iterations,
            wrap_up_seconds,
            WRAP_UP_MESSAGE,
            "review",
            usage,
        )
        return conversation

    return telemetry_priced_llm, bounded_conversation


def accumulated_usage(conversations: list[object]) -> dict[str, float]:
    """Sum cost and token counts over every conversation the run created.

    ``TaskManager`` folds each delegated review's metrics into its parent's
    ``conversation_stats`` under a ``task:`` usage id before evicting the
    sub-conversation, so the coordinator's combined metrics already cover
    delegated spend and summing here cannot double-count it.
    """
    totals = {
        "cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    for conversation in conversations:
        stats = getattr(conversation, "conversation_stats", None)
        if stats is None:
            continue
        metrics = stats.get_combined_metrics()
        cost = getattr(metrics, "accumulated_cost", 0.0)
        totals["cost"] += float(cost or 0.0)
        tokens = getattr(metrics, "accumulated_token_usage", None)
        if tokens is None:
            continue
        for key, attribute in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("cache_read_tokens", "cache_read_tokens"),
            ("cache_write_tokens", "cache_write_tokens"),
        ):
            totals[key] += int(getattr(tokens, attribute, 0) or 0)
    return totals


def table_cell(value: str) -> str:
    """Keep a value inside its table cell whatever the model identifier is."""
    escaped = value.replace("|", "\\|").replace("`", "'")
    return escaped.replace("\n", " ").strip()


def cost_is_unknown(totals: dict[str, float]) -> bool:
    """Whether spend happened but carries no price.

    A priced model never reports zero cost after real traffic, so tokens
    without cost mean LiteLLM has no pricing metadata for the model rather
    than that the review was free. Both the summary and the `cost` output
    have to agree on this: reporting an unknown spend as `0` is what makes a
    downstream budget gate pass on a review it could not price.
    """
    spent_tokens = totals["input_tokens"] or totals["output_tokens"]
    return not totals["cost"] and bool(spent_tokens)


def usage_summary(
    model: str,
    totals: dict[str, float],
    iterations: int,
    max_iterations: int,
    completed: bool,
) -> str:
    if cost_is_unknown(totals):
        rendered_cost = "Unavailable — no pricing metadata for this model"
    else:
        # Four places keep sub-cent runs legible without printing noise; the
        # action output carries the full figure for budget gates.
        rendered_cost = f"${totals['cost']:.4f}"

    rows = [
        ("Model", f"`{table_cell(model)}`"),
        ("Cost", rendered_cost),
        ("Input tokens", f"{totals['input_tokens']:,}"),
        ("Output tokens", f"{totals['output_tokens']:,}"),
    ]
    cache_read = totals["cache_read_tokens"]
    cache_write = totals["cache_write_tokens"]
    if cache_read:
        rows.append(("Cached input tokens", f"{cache_read:,}"))
    if cache_write:
        rows.append(("Cache write tokens", f"{cache_write:,}"))
    rows.append(("Coordinator iterations", f"{iterations} / {max_iterations}"))

    lines = [SUMMARY_HEADING, "", "| Metric | Value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    lines.append("")
    if not completed:
        lines.append(
            "The review did not finish; this is what it spent before failing."
        )
        lines.append("")
    lines.append(
        "Covers the review agent and any delegated sub-agents. Repository "
        "memory evaluation runs afterwards and is not included."
    )
    return "\n".join(lines) + "\n"


def append_env_file(variable: str, text: str) -> None:
    path = os.environ.get(variable)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def report_usage(
    usage: ReviewUsage,
    model: str,
    max_iterations: int,
    completed: bool,
) -> None:
    """Publish spend to the job summary and to the step's outputs.

    Runs on the failure path too, so it must not raise: a reporting problem
    must never replace or mask the review's own outcome.
    """
    try:
        totals = accumulated_usage(usage.conversations)
        summary = usage_summary(
            model,
            totals,
            usage.iterations,
            max_iterations,
            completed,
        )
        print(summary)
        append_env_file("GITHUB_STEP_SUMMARY", summary)
        # An unpriced model reports no cost rather than a zero one. A budget
        # gate comparing against an empty string fails loudly, where `0`
        # would have quietly passed a review nothing could price.
        cost = "" if cost_is_unknown(totals) else f"{totals['cost']:.6f}"
        append_env_file(
            "GITHUB_OUTPUT",
            "".join(
                f"{name}={value}\n"
                for name, value in (
                    ("cost", cost),
                    ("input_tokens", totals["input_tokens"]),
                    ("output_tokens", totals["output_tokens"]),
                    ("iterations", usage.iterations),
                )
            ),
        )
    except Exception as error:
        # Deliberately broad: this runs in a finally, where any raise would
        # replace the review's own outcome with a reporting failure.
        print(f"::warning::Could not report review usage: {error}")


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
    # Sub-agents inherit the coordinator's max_iteration_per_run as their hard
    # ceiling, so a wrap-up above it would never fire and the delegated review
    # would be cut off without ever being told to report what it found.
    if wrap_up_iterations >= max_iterations:
        raise SystemExit(
            "REVIEW_WRAP_UP_ITERATIONS must be less than MAX_REVIEW_ITERATIONS"
        )
    if subagent_wrap_up_iterations >= max_iterations:
        raise SystemExit(
            "SUBAGENT_WRAP_UP_ITERATIONS must be less than MAX_REVIEW_ITERATIONS"
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

    model = os.environ.get("LLM_MODEL", "")
    usage = ReviewUsage()
    llm_factory, conversation_factory = configured_symbols(
        model,
        wrap_up_iterations,
        wrap_up_seconds,
        max_iterations,
        usage,
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
    # Upstream reports cost only on its success path, and exits non-zero on any
    # failure. Report from here instead so a review that dies partway still
    # accounts for what it spent.
    completed = False
    try:
        agent_main()
        completed = True
    finally:
        report_usage(usage, model, max_iterations, completed)


if __name__ == "__main__":
    main()
