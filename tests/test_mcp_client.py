"""
Tests for src/pipeline/mcp_client.py
"""

import sys
import os
import pytest
import asyncio
import threading
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline import mcp_client

# Helper to ensure the background loop is running
def ensure_loop_running():
    if mcp_client._BG_LOOP is None or not mcp_client._BG_LOOP.is_running():
        mcp_client._BG_LOOP_READY = threading.Event()
        mcp_client._BG_THREAD = threading.Thread(
            target=mcp_client._start_background_loop,
            name="mcp-event-loop-test",
            daemon=True,
        )
        mcp_client._BG_THREAD.start()
        mcp_client._BG_LOOP_READY.wait()

@pytest.fixture(autouse=True)
def setup_loop():
    ensure_loop_running()
    if mcp_client._BG_LOOP is not None and mcp_client._BG_LOOP.is_running():
        fut = asyncio.run_coroutine_threadsafe(mcp_client._teardown_session(), mcp_client._BG_LOOP)
        fut.result()
    yield

class TestMcpClient:

    @patch("mcp.client.sse.sse_client")
    @patch("mcp.ClientSession")
    def test_call_tool_success(self, mock_client_session_class, mock_sse_client):
        # Setup SSE client mock
        mock_sse_ctx = AsyncMock()
        mock_sse_ctx.__aenter__.return_value = ("mock_read", "mock_write")
        mock_sse_client.return_value = mock_sse_ctx

        # Setup ClientSession mock
        mock_session = AsyncMock()
        mock_client_session_class.return_value = mock_session
        mock_session.__aenter__.return_value = mock_session
        mock_session.initialize = AsyncMock()

        # Setup tool call result
        mock_result = MagicMock()
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = "search results content"
        mock_result.content = [mock_content]
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        # Execute
        res = mcp_client.call_tool("http://localhost:3001/sse", "brave_web_search", {"query": "test"})

        # Assert
        assert len(res) == 1
        assert res[0].text == "search results content"
        mock_sse_client.assert_called_once_with(url="http://localhost:3001/sse", timeout=15)
        mock_session.call_tool.assert_called_once_with("brave_web_search", {"query": "test"})

    @patch("mcp.client.sse.sse_client")
    @patch("mcp.ClientSession")
    def test_reconnect_on_death(self, mock_client_session_class, mock_sse_client):
        # Manually teardown the session first to ensure clean state
        fut = asyncio.run_coroutine_threadsafe(mcp_client._teardown_session(), mcp_client._BG_LOOP)
        fut.result()

        # Setup SSE mock
        mock_sse_ctx = AsyncMock()
        mock_sse_ctx.__aenter__.return_value = ("mock_read", "mock_write")
        mock_sse_client.return_value = mock_sse_ctx

        # Setup ClientSession mock
        mock_session = AsyncMock()
        mock_client_session_class.return_value = mock_session
        mock_session.__aenter__.return_value = mock_session
        mock_session.initialize = AsyncMock()

        # First call raises an exception, second call succeeds
        mock_session.call_tool = AsyncMock(side_effect=[
            RuntimeError("Connection lost"),
            MagicMock(isError=False, content=["success"])
        ])

        # First call should fail and trigger session teardown
        with pytest.raises(RuntimeError, match="Connection lost"):
            mcp_client.call_tool("http://localhost:3001/sse", "brave_web_search", {"query": "fail"})

        # Second call should re-establish connection and succeed
        res = mcp_client.call_tool("http://localhost:3001/sse", "brave_web_search", {"query": "success"})
        assert res == ["success"]

    @patch("mcp.client.sse.sse_client")
    @patch("mcp.ClientSession")
    def test_timeout_behavior(self, mock_client_session_class, mock_sse_client):
        # Setup ClientSession mock where call_tool blocks/sleeps
        mock_sse_ctx = AsyncMock()
        mock_sse_ctx.__aenter__.return_value = ("mock_read", "mock_write")
        mock_sse_client.return_value = mock_sse_ctx

        mock_session = AsyncMock()
        mock_client_session_class.return_value = mock_session
        mock_session.__aenter__.return_value = mock_session
        mock_session.initialize = AsyncMock()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(2.0)
            mock_result = MagicMock()
            mock_result.isError = False
            mock_result.content = ["slow_success"]
            return mock_result

        mock_session.call_tool = AsyncMock(side_effect=slow_call)

        # Call with a short timeout
        with pytest.raises(TimeoutError):
            mcp_client.call_tool("http://localhost:3001/sse", "brave_web_search", {"query": "slow"}, timeout=0.1)

    def test_shutdown_behavior(self):
        # Call shutdown
        mcp_client.shutdown()
        
        # Give the loop thread a tiny bit of time to stop
        mcp_client._BG_THREAD.join(timeout=2.0)
        
        # The thread should not be alive
        assert not mcp_client._BG_THREAD.is_alive()
        
        # A second shutdown call should be a safe no-op
        mcp_client.shutdown()
