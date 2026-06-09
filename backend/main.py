"""
main.py — FastAPI server for DevOps Agent Visualizer
=====================================================

This file is the entry point for the backend.
It wires together:
  - FastAPI (the web framework)
  - WebSockets (for real-time streaming to the browser)
  - The agent (our AI workflow logic in agent.py)

HOW FASTAPI WORKS (beginner explanation):
-----------------------------------------
FastAPI is a Python web framework. You define "routes" which are
URLs the browser can call. Each route is just a Python function
decorated with @app.get(), @app.post(), etc.

When a request arrives, FastAPI calls your function and returns
whatever you return — usually a JSON object.

WebSockets in FastAPI use the @app.websocket() decorator. Instead
of returning a single response, the connection stays open and both
sides can send messages back and forth any time.
"""

import asyncio
import os
import uuid
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import run_agent

# ── APPLICATION SETUP ─────────────────────────────────────────
app = FastAPI(
    title="DevOps Agent Visualizer",
    description="Educational AI agent that visualizes its own workflow",
    version="1.0.0",
)

# ── CORS (Cross-Origin Resource Sharing) ──────────────────────
# When your frontend (on Vercel) calls your backend (on Render),
# the browser checks CORS headers. Without this the browser will
# block the request with a CORS error.
# "*" allows any origin — fine for a public educational project.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SESSION STORE ──────────────────────────────────────────────
# A simple in-memory dictionary that maps session_id → prompt.
# In a production app you'd use Redis or a database, but for this
# educational project a plain dict is clear and sufficient.
sessions: Dict[str, str] = {}

# ── REQUEST / RESPONSE MODELS ──────────────────────────────────
# Pydantic models tell FastAPI what shape to expect in JSON bodies.
class AskRequest(BaseModel):
    prompt: str

class AskResponse(BaseModel):
    session_id: str

# ── ROUTES ────────────────────────────────────────────────────

@app.get("/")
async def root():
    """
    Health check endpoint. Useful for Render to verify the service
    is running (Render pings / before marking the service healthy).
    """
    return {"status": "ok", "message": "DevOps Agent Visualizer backend is running"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """
    Step 1 of 2 in the agent flow.

    The frontend POSTs the user's prompt here.
    We validate it, create a session, and return a session_id.
    The frontend then opens a WebSocket to /ws/{session_id} to
    receive the real-time agent events.
    """
    prompt = request.prompt.strip()

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    if len(prompt) > 2000:
        raise HTTPException(status_code=400, detail="Prompt is too long (max 2000 characters).")

    # Generate a unique session ID for this run
    session_id = str(uuid.uuid4())
    sessions[session_id] = prompt

    return AskResponse(session_id=session_id)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    Step 2 of 2 — the real-time channel.

    HOW THIS WORKS:
    ---------------
    1. Browser opens a WebSocket to /ws/{session_id}
    2. We accept the connection
    3. We look up the prompt from our session store
    4. We call run_agent(), passing a callback function
    5. Every time the agent completes a stage, it calls the
       callback, which sends a JSON message over the WebSocket
    6. The browser receives each message and updates the UI
    7. When the agent finishes, we close the connection
    """
    await websocket.accept()

    # Look up the prompt for this session
    prompt = sessions.pop(session_id, None)  # pop → remove after retrieval
    if not prompt:
        await websocket.send_json({
            "stage": "error",
            "message": "Session not found or expired. Please try again.",
        })
        await websocket.close()
        return

    try:
        # ── CALLBACK ───────────────────────────────────────────
        # We define a small async function that the agent calls
        # every time it has something to report. This is the bridge
        # between the agent's Python logic and the WebSocket.
        async def send_event(event: dict):
            await websocket.send_json(event)

        # Run the agent — this is where all the AI work happens
        await run_agent(prompt, send_event)

    except WebSocketDisconnect:
        # The user closed the browser tab / refreshed — that's fine
        print(f"[ws] Client disconnected for session {session_id}")

    except Exception as exc:
        # Something unexpected went wrong
        print(f"[ws] Unexpected error for session {session_id}: {exc}")
        try:
            await websocket.send_json({
                "stage": "error",
                "message": f"An unexpected error occurred: {str(exc)}",
            })
        except Exception:
            pass  # Socket may already be closed

    finally:
        # Always try to close cleanly
        try:
            await websocket.close()
        except Exception:
            pass