/* ================================================================
   DevOps Agent Visualizer — script.js

   HOW THIS FILE IS ORGANIZED:
   1. Configuration
   2. DOM references
   3. WebSocket management
   4. UI update functions
   5. Feed / timeline helpers
   6. Markdown renderer (lightweight, no library needed)
   7. Event listeners
   8. Initialization

   HOW WEBSOCKETS WORK (beginner explanation):
   -------------------------------------------
   Normally a browser asks the server a question and the server
   answers once. That is called HTTP (request → response).

   WebSockets are different: they open a *persistent channel*
   between the browser and the server. Either side can send a
   message at any time without the other side having to ask first.

   This is perfect for our agent because:
     - We start the task with a regular HTTP POST (/ask)
     - The server gives us a session_id
     - We open a WebSocket to /ws/{session_id}
     - The backend sends us events as the agent works through each stage
     - We display each event in real time
   That's what makes the visualization feel "live".
================================================================ */

/* ────────────────────────────────────────────────────────────
   1. CONFIGURATION
   Change BACKEND_URL to wherever your FastAPI server lives.
   During local development:  http://localhost:8000
   After deploying to Render:  https://your-service.onrender.com
──────────────────────────────────────────────────────────── */
const BACKEND_URL = window.BACKEND_URL || "http://localhost:8000";

// Convert http:// → ws://  and  https:// → wss://
// WebSocket URLs use the ws:// protocol, not http://.
const WS_BASE = BACKEND_URL.replace(/^http/, "ws");

/* ────────────────────────────────────────────────────────────
   2. DOM REFERENCES
   Grab all the elements we'll need to update throughout the
   application lifecycle.
──────────────────────────────────────────────────────────── */
const promptInput      = document.getElementById("prompt-input");
const sendBtn          = document.getElementById("send-btn");
const sendBtnLabel     = document.getElementById("send-btn-label");
const sendBtnSpinner   = document.getElementById("send-btn-spinner");
const activityFeed     = document.getElementById("activity-feed");
const clearFeedBtn     = document.getElementById("clear-feed-btn");
const responsePanel    = document.getElementById("response-panel");
const connectionStatus = document.getElementById("connection-status");
const badgeDot         = document.querySelector(".badge-dot");

// All five timeline step elements
const timelineSteps = {
  understand: document.getElementById("stage-understand"),
  plan:       document.getElementById("stage-plan"),
  execute:    document.getElementById("stage-execute"),
  respond:    document.getElementById("stage-respond"),
  complete:   document.getElementById("stage-complete"),
};

/* ────────────────────────────────────────────────────────────
   3. STATE
   Simple object to track what's happening right now.
──────────────────────────────────────────────────────────── */
let state = {
  websocket:   null,   // The active WebSocket connection (or null)
  sessionId:   null,   // The session ID returned by POST /ask
  isRunning:   false,  // Whether the agent is currently working
};

/* ────────────────────────────────────────────────────────────
   4. WEBSOCKET MANAGEMENT

   openWebSocket(sessionId)
     Opens a WebSocket connection to /ws/{sessionId}.
     Handles: open, message, error, close events.

   closeWebSocket()
     Gracefully closes the current WebSocket if one exists.
──────────────────────────────────────────────────────────── */
function openWebSocket(sessionId) {
  const url = `${WS_BASE}/ws/${sessionId}`;
  appendFeedEntry("info", `Opening WebSocket connection…`);

  // Create the WebSocket — this immediately starts connecting
  const ws = new WebSocket(url);
  state.websocket = ws;

  // ── OPEN ──────────────────────────────────────────────────
  // Fired when the connection is successfully established.
  ws.onopen = () => {
    setConnectionStatus("connected");
    appendFeedEntry("info", "Connection established. Agent starting…");
  };

  // ── MESSAGE ───────────────────────────────────────────────
  // Fired every time the server sends us a JSON event.
  // Each event has a "stage" and a "message" field.
  ws.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      appendFeedEntry("error", "Received malformed data from server.");
      return;
    }

    // Route the event to the correct handler
    handleAgentEvent(data);
  };

  // ── ERROR ─────────────────────────────────────────────────
  ws.onerror = () => {
    appendFeedEntry("error", "WebSocket error. Check that the backend is running.");
    setConnectionStatus("error");
    setRunning(false);
  };

  // ── CLOSE ─────────────────────────────────────────────────
  ws.onclose = () => {
    setConnectionStatus("disconnected");
    setRunning(false);
  };
}

function closeWebSocket() {
  if (state.websocket) {
    state.websocket.close();
    state.websocket = null;
  }
}

/* ────────────────────────────────────────────────────────────
   5. AGENT EVENT HANDLER
   Every WebSocket message from the backend calls this function.
   The event object looks like:
     { stage: "plan", message: "Creating execution plan…" }
   Or for the final response:
     { stage: "complete", response: "## Docker Explained\n..." }
──────────────────────────────────────────────────────────── */
function handleAgentEvent(event) {
  const { stage, message, response, error } = event;

  // Always log every event to the activity feed
  if (message) {
    appendFeedEntry(stage, message);
  }

  // Advance the timeline to the current stage
  if (stage && timelineSteps[stage]) {
    activateStage(stage);
  }

  // Handle the final response payload
  if (stage === "complete" && response) {
    renderResponse(response);
    markAllComplete();
  }

  // Handle errors sent over the WebSocket
  if (stage === "error" || error) {
    appendFeedEntry("error", error || "An unknown error occurred.");
    setRunning(false);
  }
}

/* ────────────────────────────────────────────────────────────
   6. UI UPDATE FUNCTIONS
──────────────────────────────────────────────────────────── */

// setRunning(bool)
// Enables / disables the send button and toggles the spinner.
function setRunning(isRunning) {
  state.isRunning = isRunning;
  sendBtn.disabled = isRunning;
  sendBtnLabel.textContent = isRunning ? "Running…" : "Run Agent";
  sendBtnSpinner.classList.toggle("hidden", !isRunning);
}

// setConnectionStatus(status)
// Updates the header badge to show connection state.
function setConnectionStatus(status) {
  const labels = {
    connecting:   "Connecting…",
    connected:    "Connected",
    disconnected: "Disconnected",
    error:        "Error",
  };
  connectionStatus.textContent = labels[status] || status;
  badgeDot.className = `badge-dot ${status}`;
}

// resetUI()
// Clears the timeline and response panel before a new run.
function resetUI() {
  // Remove active/done classes from all timeline steps
  Object.values(timelineSteps).forEach((el) => {
    el.classList.remove("active", "done");
  });

  // Clear the response panel
  responsePanel.innerHTML = `<p class="response-empty">The agent's complete answer will appear here.</p>`;

  // Clear the feed
  activityFeed.innerHTML = "";
}

// activateStage(stageName)
// Marks previous stages as done and the current stage as active.
function activateStage(stageName) {
  const stageOrder = ["understand", "plan", "execute", "respond", "complete"];
  const currentIndex = stageOrder.indexOf(stageName);

  stageOrder.forEach((name, index) => {
    const el = timelineSteps[name];
    if (!el) return;

    if (index < currentIndex) {
      // This stage comes before the current one → mark as done
      el.classList.remove("active");
      el.classList.add("done");
    } else if (index === currentIndex) {
      // This IS the current stage → highlight it
      el.classList.add("active");
      el.classList.remove("done");
    }
  });
}

// markAllComplete()
// Called when the agent finishes — marks every stage as done.
function markAllComplete() {
  Object.values(timelineSteps).forEach((el) => {
    el.classList.remove("active");
    el.classList.add("done");
  });
  setRunning(false);
}

/* ────────────────────────────────────────────────────────────
   7. FEED HELPERS
──────────────────────────────────────────────────────────── */

// appendFeedEntry(stage, message)
// Creates a timestamped row in the activity feed.
function appendFeedEntry(stage, message) {
  // Remove the "empty" placeholder if it's still there
  const empty = activityFeed.querySelector(".feed-empty");
  if (empty) empty.remove();

  const now  = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false,
    hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const entry = document.createElement("div");
  entry.className = `feed-entry stage-${stage}`;
  entry.innerHTML = `
    <span class="feed-time">${time}</span>
    <span class="feed-message">${escapeHtml(message)}</span>
  `;

  activityFeed.appendChild(entry);

  // Auto-scroll to the newest message
  activityFeed.scrollTop = activityFeed.scrollHeight;
}

/* ────────────────────────────────────────────────────────────
   8. LIGHTWEIGHT MARKDOWN RENDERER
   We don't want to load a full library like marked.js just for
   this project. This function handles the most common Markdown
   patterns the LLM will produce.
──────────────────────────────────────────────────────────── */
function renderMarkdown(text) {
  // Protect code blocks first (replace with placeholders so
  // we don't accidentally format their contents)
  const codeBlocks = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`);
    return `%%CODE_BLOCK_${idx}%%`;
  });

  // Inline code
  text = text.replace(/`([^`]+)`/g, (_, code) => `<code>${escapeHtml(code)}</code>`);

  // Bold **text** or __text__
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__(.+?)__/g, "<strong>$1</strong>");

  // Italic *text* or _text_
  text = text.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  text = text.replace(/_([^_]+)_/g, "<em>$1</em>");

  // Headings
  text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Blockquotes
  text = text.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

  // Unordered lists (lines starting with - or *)
  text = text.replace(/(^[-*] .+$(\n|$))+/gm, (block) => {
    const items = block.trim().split("\n")
      .map((line) => `<li>${line.replace(/^[-*] /, "")}</li>`)
      .join("");
    return `<ul>${items}</ul>`;
  });

  // Ordered lists
  text = text.replace(/(^\d+\. .+$(\n|$))+/gm, (block) => {
    const items = block.trim().split("\n")
      .map((line) => `<li>${line.replace(/^\d+\. /, "")}</li>`)
      .join("");
    return `<ol>${items}</ol>`;
  });

  // Paragraphs (double newlines)
  text = text.replace(/\n\n+/g, "</p><p>");
  text = `<p>${text}</p>`;

  // Restore code blocks
  codeBlocks.forEach((block, idx) => {
    text = text.replace(`%%CODE_BLOCK_${idx}%%`, block);
  });

  return text;
}

// renderResponse(text)
// Renders the final AI response into the response panel.
function renderResponse(text) {
  responsePanel.innerHTML = renderMarkdown(text);
}

// escapeHtml(str)
// Prevents XSS by escaping < > & " ' characters.
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* ────────────────────────────────────────────────────────────
   9. MAIN ACTION — submitPrompt()
   This is called when the user clicks "Run Agent".
   Flow:
     1. Validate the prompt
     2. Reset the UI
     3. POST to /ask → get session_id
     4. Open WebSocket to /ws/{session_id}
──────────────────────────────────────────────────────────── */
async function submitPrompt() {
  const prompt = promptInput.value.trim();

  // Validate
  if (!prompt) {
    appendFeedEntry("error", "Please enter a prompt before running the agent.");
    return;
  }
  if (state.isRunning) return;

  // Prepare UI
  resetUI();
  setRunning(true);
  appendFeedEntry("info", `Sending prompt to backend…`);

  try {
    // ── STEP 1: POST /ask ─────────────────────────────────
    // We send the prompt to the backend and receive a session_id.
    // The session_id is used to identify our WebSocket connection.
    const res = await fetch(`${BACKEND_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail || `Server error ${res.status}`);
    }

    const { session_id } = await res.json();
    state.sessionId = session_id;
    appendFeedEntry("info", `Session ID: ${session_id}`);

    // ── STEP 2: Open WebSocket ────────────────────────────
    // Now that we have a session_id we can subscribe to
    // the agent's real-time event stream.
    openWebSocket(session_id);

  } catch (err) {
    appendFeedEntry("error", `Failed to start agent: ${err.message}`);
    setRunning(false);
  }
}

/* ────────────────────────────────────────────────────────────
   10. EVENT LISTENERS
──────────────────────────────────────────────────────────── */

// Send on button click
sendBtn.addEventListener("click", submitPrompt);

// Send on Ctrl+Enter inside the textarea
promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    submitPrompt();
  }
});

// Clear activity feed
clearFeedBtn.addEventListener("click", () => {
  activityFeed.innerHTML = `<p class="feed-empty">Agent output will appear here once you submit a prompt.</p>`;
});

// Quick-fill chips
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    promptInput.value = chip.dataset.text;
    promptInput.focus();
  });
});

/* ────────────────────────────────────────────────────────────
   11. INITIALIZATION
──────────────────────────────────────────────────────────── */
setConnectionStatus("disconnected");