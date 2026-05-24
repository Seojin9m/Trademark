"""Per-request user context for the chat agent.

LangChain tools are plain functions registered with ``@tool`` — there's no
clean way to pass extra arguments through the agent's invocation. We use a
``contextvars.ContextVar`` so ``stream_chat`` can set the current user_id
once per request and every tool can read it via ``get_current_user_id()``.

ContextVar is the right primitive here (vs threading.local) because
StreamingResponse runs inside an asyncio event loop and the agent's tool
calls may bounce across coroutine yield points.
"""

from __future__ import annotations

from contextvars import ContextVar

_current_user_id: ContextVar[str | None] = ContextVar("trademark.chat.user_id", default=None)


def set_current_user_id(user_id: str | None) -> None:
    _current_user_id.set(user_id)


def get_current_user_id() -> str | None:
    return _current_user_id.get()


def require_current_user_id() -> str:
    uid = _current_user_id.get()
    if not uid:
        raise RuntimeError(
            "No current user_id in chat context. The /api/chat endpoint should "
            "call set_current_user_id() before invoking the agent."
        )
    return uid
