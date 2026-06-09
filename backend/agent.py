"""
agent.py — The AI Agent Workflow
=================================

WHAT IS AN AGENT? (beginner explanation)
-----------------------------------------
A regular AI chatbot does this:
  User asks question → AI answers → Done.

An agent does this:
  User gives a goal →
    Agent UNDERSTANDS the goal →
    Agent makes a PLAN →
    Agent EXECUTES each step of the plan →
    Agent composes a final RESPONSE →
    Agent reports COMPLETION

The key insight: an agent *reasons about what to do*, not just
about what to say. It breaks work into stages, can (in principle)
use tools, and reports progress along the way.

WHY SEPARATE PLANNING FROM EXECUTION?
--------------------------------------
When you ask an AI to "generate a Dockerfile", mixing planning
and execution in one step often produces disorganized output.

By separating them:
  Plan  = "What steps should I take?"  (structured thinking)
  Execute = "Do each step"             (focused work per step)

The plan acts like a scaffold. Each execution step can focus
on one thing. The result is more organized and educational.

THIS FILE'S STRUCTURE:
----------------------
  run_agent()    — main loop that calls all stages in order
  understand()   — analyze the user's prompt
  plan()         — ask Groq to create a step-by-step plan
  execute()      — simulate running each plan step
  respond()      — ask Groq for the final comprehensive answer
  finish()       — send the completion event
"""

import asyncio
from typing import Callable, Awaitable
from groq_client import generate_plan, generate_response

# ── TYPE ALIAS ────────────────────────────────────────────────
# A "SendEvent" is any async function that takes a dict and
# sends it to the WebSocket client.
SendEvent = Callable[[dict], Awaitable[None]]

# ── HOW LONG TO PAUSE BETWEEN STAGE EVENTS (seconds) ─────────
# Small delays make the stages visible in the UI.
# Without them everything would flash by too fast to read.
STAGE_DELAY   = 0.6   # pause between major stage announcements
STEP_DELAY    = 1.0   # pause between individual execution steps

# ── MAIN AGENT LOOP ───────────────────────────────────────────
async def run_agent(prompt: str, send_event: SendEvent) -> None:
    """
    Runs the complete 5-stage agent loop.
    Calls send_event() at each meaningful moment so the browser
    can update the UI in real time.

    Stages:
      1. Understand → parse and categorize the prompt
      2. Plan       → generate a step-by-step plan using Groq
      3. Execute    → simulate working through each plan step
      4. Respond    → generate the final answer using Groq
      5. Complete   → send the final response and finish
    """
    try:
        # ── STAGE 1: UNDERSTAND ───────────────────────────────
        intent, category = await understand(prompt, send_event)

        # ── STAGE 2: PLAN ─────────────────────────────────────
        plan_steps = await plan(prompt, intent, category, send_event)

        # ── STAGE 3: EXECUTE ──────────────────────────────────
        await execute(plan_steps, send_event)

        # ── STAGE 4: RESPOND ──────────────────────────────────
        final_answer = await respond(prompt, plan_steps, send_event)

        # ── STAGE 5: COMPLETE ─────────────────────────────────
        await finish(final_answer, send_event)

    except Exception as exc:
        # If anything goes wrong, report it over the WebSocket
        await send_event({
            "stage": "error",
            "message": f"Agent error: {str(exc)}",
        })
        raise  # Re-raise so main.py can also log it


# ─────────────────────────────────────────────────────────────
# STAGE 1: UNDERSTAND
# -----------------------------------------------------------------
# The agent reads the prompt and tries to figure out:
#   - The user's intent (what do they want?)
#   - The category (explain / generate / troubleshoot / other)
#
# For this educational project we classify locally with simple
# keyword matching — no extra LLM call needed for this step.
# In a real production agent this might call a classifier model.
# ─────────────────────────────────────────────────────────────
async def understand(prompt: str, send_event: SendEvent) -> tuple[str, str]:
    await send_event({
        "stage": "understand",
        "message": "Understanding request…",
    })
    await asyncio.sleep(STAGE_DELAY)

    # Simple keyword-based classification
    lower = prompt.lower()

    if any(kw in lower for kw in ["explain", "what is", "what are", "how does", "describe"]):
        category = "explanation"
        intent   = "Explain a DevOps concept"
    elif any(kw in lower for kw in ["generate", "create", "write", "build", "scaffold"]):
        category = "generation"
        intent   = "Generate a configuration or code artifact"
    elif any(kw in lower for kw in ["troubleshoot", "fix", "debug", "error", "issue", "crash", "fail"]):
        category = "troubleshooting"
        intent   = "Diagnose and resolve a DevOps problem"
    else:
        category = "general"
        intent   = "Provide DevOps guidance"

    await send_event({
        "stage": "understand",
        "message": f"Intent detected: {intent} (category: {category})",
    })
    await asyncio.sleep(STAGE_DELAY)

    await send_event({
        "stage": "understand",
        "message": "Prompt analysis complete. Moving to planning…",
    })

    return intent, category


# ─────────────────────────────────────────────────────────────
# STAGE 2: PLAN
# -----------------------------------------------------------------
# We ask Groq to give us 3–5 concrete steps for the task.
# This is what makes our system an "agent" rather than a plain
# chatbot: it *decides what to do* before doing it.
#
# The plan comes back as a numbered list which we parse into
# a Python list of strings so we can loop over them in Execute.
# ─────────────────────────────────────────────────────────────
async def plan(
    prompt: str,
    intent: str,
    category: str,
    send_event: SendEvent,
) -> list[str]:
    await send_event({
        "stage": "plan",
        "message": "Generating execution plan…",
    })
    await asyncio.sleep(STAGE_DELAY)

    # Ask Groq to create a plan
    plan_text = await generate_plan(prompt, intent, category)

    # Parse the numbered list into a Python list
    # We handle lines like "1. Do something" or "- Do something"
    steps = []
    for line in plan_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading numbers, dashes, dots
        cleaned = line.lstrip("0123456789.-) ").strip()
        if cleaned:
            steps.append(cleaned)

    # Fallback in case parsing produces nothing useful
    if not steps:
        steps = [
            "Analyze the request context",
            "Gather relevant technical details",
            "Formulate the response",
        ]

    # Cap at 5 steps to keep the UI tidy
    steps = steps[:5]

    # Send each step to the feed so the user can see the plan
    await send_event({
        "stage": "plan",
        "message": f"Plan created with {len(steps)} steps:",
    })
    await asyncio.sleep(0.3)

    for i, step in enumerate(steps, 1):
        await send_event({
            "stage": "plan",
            "message": f"  Step {i}: {step}",
        })
        await asyncio.sleep(0.2)

    await send_event({
        "stage": "plan",
        "message": "Plan complete. Beginning execution…",
    })

    return steps


# ─────────────────────────────────────────────────────────────
# STAGE 3: EXECUTE
# -----------------------------------------------------------------
# WHY IS EXECUTION SEPARATE FROM PLANNING?
# -----------------------------------------
# Planning = deciding *what* to do (high-level reasoning)
# Execution = doing each step  (focused, concrete work)
#
# Separating them makes each stage easier to observe and debug.
# In a real agent this is where you'd call external tools:
# run shell commands, query APIs, read files, etc.
#
# For this educational project we SIMULATE execution with
# time delays so you can watch the stages tick by.
# Real execution of Docker / K8s / Terraform commands would
# require secure sandboxing — well beyond a beginner project.
# ─────────────────────────────────────────────────────────────
async def execute(steps: list[str], send_event: SendEvent) -> None:
    await send_event({
        "stage": "execute",
        "message": "Starting execution phase…",
    })
    await asyncio.sleep(STAGE_DELAY)

    for i, step in enumerate(steps, 1):
        # Announce the step
        await send_event({
            "stage": "execute",
            "message": f"Executing Step {i}: {step}",
        })

        # Simulate doing actual work — in a real agent this would
        # call a tool (e.g. Docker API, kubectl, Terraform CLI)
        await asyncio.sleep(STEP_DELAY)

        # Report completion
        await send_event({
            "stage": "execute",
            "message": f"Step {i} complete ✓",
        })
        await asyncio.sleep(0.3)

    await send_event({
        "stage": "execute",
        "message": f"All {len(steps)} steps executed. Generating response…",
    })


# ─────────────────────────────────────────────────────────────
# STAGE 4: RESPOND
# -----------------------------------------------------------------
# Now we have:
#   - The original prompt
#   - The execution plan (what we decided to do)
# We feed both to Groq and ask for a comprehensive final answer.
# ─────────────────────────────────────────────────────────────
async def respond(
    prompt: str,
    plan_steps: list[str],
    send_event: SendEvent,
) -> str:
    await send_event({
        "stage": "respond",
        "message": "Generating final response with Groq AI…",
    })
    await asyncio.sleep(STAGE_DELAY)

    # Ask Groq for the final answer
    answer = await generate_response(prompt, plan_steps)

    await send_event({
        "stage": "respond",
        "message": "Response generated. Finalizing…",
    })
    await asyncio.sleep(0.5)

    return answer


# ─────────────────────────────────────────────────────────────
# STAGE 5: COMPLETE
# -----------------------------------------------------------------
# We send the final response payload.
# The frontend listens for stage == "complete" and renders
# the `response` field in the Final Response Panel.
# ─────────────────────────────────────────────────────────────
async def finish(final_answer: str, send_event: SendEvent) -> None:
    await send_event({
        "stage": "complete",
        "message": "Task completed successfully.",
        "response": final_answer,
    })