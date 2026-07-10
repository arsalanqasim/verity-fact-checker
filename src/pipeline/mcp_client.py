"""
Persistent MCP Client Connection Manager

Provides a persistent connection wrapper around the Brave Search MCP server,
avoiding the need to open and close connections for every single query.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class PersistentMCPClient:
    def __init__(self, mcp_url: str):
        self.mcp_url = mcp_url
        self._session = None
        self._ctx = None
        self._lock = asyncio.Lock()

    async def get_session(self):
        """Lazy-initializes and returns the persistent ClientSession."""
        async with self._lock:
            if self._session is not None:
                return self._session

            logger.info(f"Establishing persistent MCP connection to {self.mcp_url}...")
            from mcp.client.sse import sse_client
            from mcp import ClientSession

            try:
                self._ctx = sse_client(url=self.mcp_url, timeout=15)
                read, write = await self._ctx.__aenter__()
                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()
                self._session = session
                logger.info("Persistent MCP connection initialized successfully.")
                return self._session
            except Exception as exc:
                logger.error(f"Failed to initialize persistent MCP connection: {exc}")
                await self._cleanup_unsafe()
                raise

    async def _cleanup_unsafe(self):
        """Performs cleanup without acquiring the lock (internal helper)."""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning(f"Error exiting MCP session context: {exc}")
            self._session = None

        if self._ctx is not None:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning(f"Error exiting MCP SSE context: {exc}")
            self._ctx = None

    async def close(self):
        """Closes the persistent connection context."""
        async with self._lock:
            logger.info("Closing persistent MCP connection...")
            await self._cleanup_unsafe()
            logger.info("Persistent MCP connection closed.")


# Global singleton instance cache
_instances: dict[str, PersistentMCPClient] = {}

def get_mcp_client(mcp_url: str) -> PersistentMCPClient:
    """Return the global PersistentMCPClient for the specified URL."""
    url = mcp_url.strip()
    if url not in _instances:
        _instances[url] = PersistentMCPClient(url)
    return _instances[url]
