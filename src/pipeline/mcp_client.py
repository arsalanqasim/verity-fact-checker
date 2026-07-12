"""
MCP Client — Background Loop Transport

Design
------
``asyncio.run()`` creates a brand-new event loop on every invocation.  Any
``asyncio`` primitive (Lock, Queue, …) that was created on a *different* loop
will raise "bound to a different event loop" when awaited.  A module-level
singleton that holds an ``asyncio.Lock`` is therefore incompatible with callers
that use ``asyncio.run()``.

Fix: one dedicated background ``threading.Thread`` that owns a single
``asyncio`` event loop for the **entire process lifetime**.  The MCP session
lives exclusively on that loop, so all its internal locks are always awaited
from the correct loop.

Synchronous callers (e.g. ``verify_claim``) submit coroutines via
``asyncio.run_coroutine_threadsafe(coro, _BG_LOOP)`` and block on the
resulting ``concurrent.futures.Future``.  This is the standard, documented
pattern for bridging sync and async code across threads.

Public API
----------
``call_tool(mcp_url, tool_name, args, timeout) -> list[Any]``
    Synchronous.  Sends one JSON-RPC tool call to the MCP server and returns
    the result content list.  Creates (or reuses) a persistent session on the
    background loop.  If the session has died, reconnects transparently.

``shutdown()``
    Gracefully close the MCP session and stop the background loop.  Call at
    process exit (optional — the daemon thread will be reaped automatically).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Background event loop — one per process, lives forever
# ---------------------------------------------------------------------------

_BG_LOOP: asyncio.AbstractEventLoop | None = None
_BG_LOOP_READY = threading.Event()


def _start_background_loop() -> None:
    global _BG_LOOP
    _BG_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_BG_LOOP)
    _BG_LOOP_READY.set()
    _BG_LOOP.run_forever()


_BG_THREAD = threading.Thread(
    target=_start_background_loop,
    name="mcp-event-loop",
    daemon=True,  # reaped automatically when the process exits
)
_BG_THREAD.start()
_BG_LOOP_READY.wait()  # block until the loop is actually running


def _submit(coro) -> Any:
    """Submit a coroutine to the background loop and block until it completes."""
    fut = asyncio.run_coroutine_threadsafe(coro, _BG_LOOP)  # type: ignore[arg-type]
    return fut.result()  # blocks the calling thread; raises on exception


# ---------------------------------------------------------------------------
# Persistent MCP session (lives on the background loop)
# ---------------------------------------------------------------------------

_TOOL_NAME = "brave_web_search"

# Module-level session state.  Only ever touched from _BG_LOOP.
_session = None
_ctx = None
_session_url: str | None = None
_session_lock: asyncio.Lock | None = None


async def _ensure_session(mcp_url: str) -> Any:
    """
    Return a live ``ClientSession``, (re)connecting if necessary.
    Must be called from the background loop only.
    """
    global _session, _ctx, _session_url, _session_lock

    if _session_lock is None:
        _session_lock = asyncio.Lock()

    async with _session_lock:
        # Reuse existing session for the same URL
        if _session is not None and _session_url == mcp_url:
            return _session

        # Different URL or session died — clean up first
        await _teardown_session()

        logger.info("Establishing MCP connection to %s …", mcp_url)
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        _ctx = sse_client(url=mcp_url, timeout=15)
        read, write = await _ctx.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()

        _session = session
        _session_url = mcp_url
        logger.info("MCP session ready.")
        return _session


async def _teardown_session() -> None:
    """Close the current session + SSE context.  Safe to call when both are None."""
    global _session, _ctx, _session_url
    if _session is not None:
        try:
            await _session.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug("Error closing MCP session: %s", exc)
        _session = None
    if _ctx is not None:
        try:
            await _ctx.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug("Error closing SSE context: %s", exc)
        _ctx = None
    _session_url = None


async def _call_tool_async(
    mcp_url: str,
    tool_name: str,
    args: dict,
) -> list:
    """
    Async implementation — runs on the background loop.
    Opens (or reuses) the session, calls the tool, returns content list.
    On any transport error, invalidates the session so the next call reconnects.
    """
    try:
        session = await _ensure_session(mcp_url)
        result = await session.call_tool(tool_name, args)
    except Exception as exc:
        logger.warning("MCP call failed (%s); invalidating session for reconnect.", exc)
        await _teardown_session()
        raise

    if result.isError:
        raise RuntimeError(
            f"MCP tool '{tool_name}' returned an error for args {args}"
        )
    return list(result.content)


# ---------------------------------------------------------------------------
# Public synchronous API
# ---------------------------------------------------------------------------

def call_tool(
    mcp_url: str,
    tool_name: str = _TOOL_NAME,
    args: dict | None = None,
    timeout: float = 30.0,
) -> list:
    """
    Synchronous.  Call an MCP tool and return the result content list.

    Submits the async work to the dedicated background event loop via
    ``run_coroutine_threadsafe``, then blocks the calling thread until the
    result is ready.  The calling thread's own event loop (if any) is
    unaffected.

    Parameters
    ----------
    mcp_url:
        SSE endpoint of the MCP server, e.g. ``http://localhost:3001/sse``.
    tool_name:
        Name of the MCP tool to invoke.
    args:
        Tool arguments dict.
    timeout:
        Seconds to wait before raising ``TimeoutError``.

    Returns
    -------
    list
        The ``CallToolResult.content`` list from the MCP server.
    """
    if args is None:
        args = {}

    fut = asyncio.run_coroutine_threadsafe(
        _call_tool_async(mcp_url, tool_name, args),
        _BG_LOOP,  # type: ignore[arg-type]
    )
    return fut.result(timeout=timeout)


def shutdown() -> None:
    """
    Gracefully close the MCP session and stop the background loop.
    Optional — the daemon thread is reaped automatically at process exit.
    """
    if _BG_LOOP is not None and _BG_LOOP.is_running():
        try:
            _submit(_teardown_session())
        except Exception:
            pass
        _BG_LOOP.call_soon_threadsafe(_BG_LOOP.stop)
