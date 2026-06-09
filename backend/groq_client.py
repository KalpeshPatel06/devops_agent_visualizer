"""
groq_client.py — Groq API Integration
======================================

This module is the only place in the project that talks to the
Groq LLM API. Keeping all AI calls in one file makes it easy to:
  - Swap Groq for another provider (OpenAI, Anthropic, etc.)
  - Change the model in one place
  - Add retry logic or caching without touching the agent logic

HOW THE GROQ API WORKS:
-----------------------
Groq hosts open-source models (like LLaMA 3) and exposes them
via an OpenAI-compatible REST API. You send a list of messages
(system prompt + user message) and get back the model's reply.

We use the official `groq` Python SDK which wraps the HTTP calls.

ENVIRONMENT VARIABLES:
  GROQ_API_KEY   — your Groq API key (required)
  GROQ_MODEL     — model name (optional, defaults to llama-3.3-70b-versatile)
"""

import os
import asyncio
from groq import AsyncGroq  # Async client for use with FastAPI

# ── MODEL CONFIGURATION ───────────────────────────────────────
# Change this to any model available on your Groq account.
# At the time of writing the free tier supports:
#   llama-3.3-70b-versatile   (default — good balance of speed / quality)
#   llama-3.1-8b-instant      (faster, smaller)
#   mixtral-8x7b-32768        (good for long contexts)
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MODEL = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

# ── CLIENT INITIALIZATION ─────────────────────────────────────
# AsyncGroq reads GROQ_API_KEY from the environment automatically.
# If the key is missing, it raises an AuthenticationError on the
# first API call (not at import time).
def _get_client() -> AsyncGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY environment variable is not set. "
            "Get your key at https://console.groq.com and add it to your .env file."
        )
    return AsyncGroq(api_key=api_key)


# ── SYSTEM PROMPT ─────────────────────────────────────────────
# This is the "persona" we give the AI. It shapes tone, format,
# and domain focus for every response.
SYSTEM_PROMPT = """You are an expert DevOps engineer and educator.
Your job is to help developers understand and implement DevOps concepts
including Docker, Kubernetes, CI/CD pipelines, Terraform, GitHub Actions,
and cloud infrastructure.

Always:
- Use clear, beginner-friendly language
- Provide practical, working examples
- Format output with Markdown (use headers, code blocks, bullet points)
- Explain *why* not just *what*
- Use real-world analogies when helpful

When generating code or configuration files, ensure they are:
- Complete and immediately usable
- Well-commented
- Following industry best practices"""


# ─────────────────────────────────────────────────────────────
# generate_plan(prompt, intent, category) → str
# -----------------------------------------------------------------
# Called during the Plan stage.
# Asks Groq to break the task into 3–5 concrete numbered steps.
# Returns the raw text so agent.py can parse it into a list.
# ─────────────────────────────────────────────────────────────
async def generate_plan(prompt: str, intent: str, category: str) -> str:
    """
    Ask Groq to create a numbered execution plan for the given prompt.
    Returns a plain-text numbered list, e.g.:
      1. Analyze requirements
      2. Generate Dockerfile
      3. Explain each instruction
      4. Suggest optimizations
    """
    client = _get_client()

    planning_prompt = f"""
You are planning how to answer the following DevOps request.

Request: {prompt}
Intent:  {intent}
Category: {category}

Create a numbered list of 3 to 5 specific, actionable steps you will take
to answer this request thoroughly.

Rules:
- Each step must be on its own line starting with a number and period (e.g. "1. ")
- Keep each step concise (under 15 words)
- Steps should be logical and sequential
- Do NOT include any preamble, explanation, or conclusion
- Output ONLY the numbered list, nothing else

Example format:
1. Analyze the Flask application requirements
2. Define the base Docker image
3. Configure the working directory and dependencies
4. Set up the entry point command
5. Add optimization recommendations
"""

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": planning_prompt},
            ],
            max_tokens=300,
            temperature=0.3,  # Low temperature → more deterministic planning
        )
        return response.choices[0].message.content.strip()

    except Exception as exc:
        # Return a minimal fallback plan so the agent can continue
        print(f"[groq] Planning error: {exc}")
        return "1. Analyze the request\n2. Research relevant information\n3. Compose the answer"


# ─────────────────────────────────────────────────────────────
# generate_response(prompt, plan_steps) → str
# -----------------------------------------------------------------
# Called during the Respond stage.
# Sends the original prompt + execution plan to Groq and asks
# for the final comprehensive answer.
# Returns Markdown-formatted text which the frontend renders.
# ─────────────────────────────────────────────────────────────
async def generate_response(prompt: str, plan_steps: list[str]) -> str:
    """
    Ask Groq to generate the full, detailed answer.
    The plan steps are included so the answer covers every
    planned topic in a structured way.
    """
    client = _get_client()

    steps_text = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan_steps))

    response_prompt = f"""
Answer the following DevOps request comprehensively and practically.

Request: {prompt}

Your execution plan was:
{steps_text}

Follow the execution plan as a structural guide. Provide:
- Clear explanations with real-world context
- Working code examples in fenced code blocks with the correct language tag
- Best practices and common pitfalls
- Next steps or further learning suggestions

Format the response with Markdown: use ## headers, bullet points, and
fenced code blocks. Make it educational and beginner-friendly.
"""

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": response_prompt},
            ],
            max_tokens=2000,
            temperature=0.5,  # Slightly creative but still accurate
        )
        return response.choices[0].message.content.strip()

    except Exception as exc:
        print(f"[groq] Response generation error: {exc}")
        return (
            "## Error Generating Response\n\n"
            f"The AI model returned an error: `{str(exc)}`\n\n"
            "**Possible causes:**\n"
            "- Invalid or missing GROQ_API_KEY\n"
            "- Model rate limit reached\n"
            "- Network connectivity issue\n\n"
            "Please check your `.env` file and Groq account, then try again."
        )