"""LangChain ReAct agent for the 'Talk to My Data' chatbot."""

import sys
import time
import uuid
from collections import deque
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.chat.tools import ALL_TOOLS


# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a quant trading assistant for a personal tech-stock portfolio management system called Trade4Me.

You have access to real-time portfolio data, factor scores, trade proposals, execution history, risk metrics, news research, and self-learning analytics.

## Your capabilities
- Answer questions about the current portfolio (positions, weights, P&L)
- Explain trade proposals — why signals fired, what the judge decided, and why
- Analyze factor scores and explain what they mean for specific stocks
- Discuss risk metrics, sector concentration, and drawdown levels
- Summarize news research and sentiment for stocks
- Review historical performance and learning outcomes
- Explain the trading strategy, pipeline logic, and adaptive parameters
- Search the web for up-to-date information (web_search) and fetch the text of
  any link the user shares (fetch_url). Use these whenever the user asks about
  current events, recent news, or shares a URL.

## Guidelines
- Be concise and direct. Use numbers and data, not vague statements.
- When the user asks about a specific ticker or proposal, fetch the relevant data first.
- If data is unavailable, say so clearly — don't guess or hallucinate numbers.
- Format currency values with $ and percentages with %. Use 2 decimal places.
- When discussing trade proposals, reference the judge verdict and confidence level.
- You can discuss general stock market concepts, but always ground answers in the user's actual data when possible.
- The portfolio is a diversified US equities portfolio spanning all 11 GICS sectors, managed by a quantitative factor model. It is benchmarked against SPY (broad market) with QQQ as a secondary tech-tilt reference.
- The user is a retail investor — explain quant concepts clearly when needed but don't over-explain for simple questions.
"""

# ─── Session storage ─────────────────────────────────────────────────────────

_sessions: dict[str, dict] = {}


def _cleanup_expired():
    """Remove sessions older than TTL."""
    ttl = settings.chatbot.session_ttl_minutes * 60
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["last_active"] > ttl]
    for sid in expired:
        del _sessions[sid]


def get_or_create_session(session_id: str | None = None) -> tuple[str, list]:
    """Return (session_id, message_history). Creates new session if needed."""
    _cleanup_expired()

    if session_id and session_id in _sessions:
        _sessions[session_id]["last_active"] = time.time()
        return session_id, _sessions[session_id]["messages"]

    sid = session_id or str(uuid.uuid4())[:12]
    _sessions[sid] = {
        "messages": [],
        "last_active": time.time(),
    }
    return sid, _sessions[sid]["messages"]


def delete_session(session_id: str) -> bool:
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


# ─── Agent creation ──────────────────────────────────────────────────────────

def _create_agent():
    """Create the LangChain ReAct agent with all tools."""
    llm = ChatAnthropic(
        model=settings.chatbot.model,
        temperature=settings.chatbot.temperature,
        api_key=settings.api_keys.anthropic_api_key,
        max_tokens=2048,
    )
    return create_react_agent(llm, ALL_TOOLS)


# Lazy singleton
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = _create_agent()
    return _agent


# ─── Streaming chat ─────────────────────────────────────────────────────────

async def stream_chat(session_id: str | None, user_message: str):
    """Async generator that yields SSE-formatted events.

    Events:
      - {"type": "session", "session_id": "..."}
      - {"type": "tool_start", "tool": "...", "input": "..."}
      - {"type": "tool_end", "tool": "..."}
      - {"type": "token", "content": "..."}
      - {"type": "done"}
      - {"type": "error", "message": "..."}
    """
    import json

    sid, history = get_or_create_session(session_id)
    yield f"data: {json.dumps({'type': 'session', 'session_id': sid})}\n\n"

    # Build messages for the agent
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    # Add conversation history (capped)
    max_hist = settings.chatbot.max_history
    for msg in history[-max_hist:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=user_message))

    # Save user message to history
    history.append({"role": "user", "content": user_message})

    try:
        agent = _get_agent()
        full_response = ""
        # Track whether a tool call happened since the last text chunk. When
        # the assistant emits text → tool_call → more text, we need to insert
        # a paragraph break so the two text segments don't run together.
        saw_tool_since_last_text = False
        # Batch outgoing text. Anthropic streams characters one at a time, so
        # without batching a 3000-char response is ~1500 SSE events for the
        # frontend to parse. Flushing at ~40 chars cuts that ~20×.
        text_buffer = ""
        BATCH_SIZE = 40

        def flush_buffer():
            nonlocal text_buffer
            if not text_buffer:
                return None
            payload = f"data: {json.dumps({'type': 'token', 'content': text_buffer})}\n\n"
            text_buffer = ""
            return payload

        async for event in agent.astream_events(
            {"messages": messages},
            version="v2",
        ):
            kind = event.get("event", "")

            if kind == "on_tool_start":
                # Flush any pending text before the tool boundary so events arrive in order
                pending = flush_buffer()
                if pending:
                    yield pending
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", "")
                yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'input': str(tool_input)[:200]})}\n\n"

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                saw_tool_since_last_text = True
                yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name})}\n\n"

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if not chunk or not hasattr(chunk, "content"):
                    continue
                # Anthropic returns content as either str or list of content blocks
                content = chunk.content
                text_pieces = []
                if isinstance(content, str):
                    if content:
                        text_pieces.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text" and block.get("text"):
                                text_pieces.append(block["text"])
                            elif block.get("type") == "text_delta" and block.get("text"):
                                text_pieces.append(block["text"])
                        elif isinstance(block, str) and block:
                            text_pieces.append(block)
                for piece in text_pieces:
                    # Insert a paragraph break when text resumes after a tool call.
                    if (
                        saw_tool_since_last_text
                        and full_response
                        and not full_response.endswith("\n\n")
                    ):
                        text_buffer += "\n\n"
                        full_response += "\n\n"
                    saw_tool_since_last_text = False
                    text_buffer += piece
                    full_response += piece
                    if len(text_buffer) >= BATCH_SIZE:
                        pending = flush_buffer()
                        if pending:
                            yield pending

        # Flush any remaining buffered text
        pending = flush_buffer()
        if pending:
            yield pending

        # Save assistant response to history
        if full_response:
            history.append({"role": "assistant", "content": full_response})

        # Trim history if too long
        max_hist = settings.chatbot.max_history
        while len(history) > max_hist:
            history.pop(0)

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
