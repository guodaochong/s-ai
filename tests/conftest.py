from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


@pytest.fixture
def isolated_state(monkeypatch):
    """Reset _tool_cache, _circuit_breaker, _last_cache_sweep for test isolation."""
    from app import config
    monkeypatch.setattr(config, "_tool_cache", OrderedDict())
    monkeypatch.setattr(config, "_circuit_breaker", {})
    monkeypatch.setattr(config, "_last_cache_sweep", 0.0)
    return config


@pytest.fixture
def mock_call_llm():
    """Mock app.llm.call_llm. Default return: ("content", "reasoning", [])."""
    with patch("app.llm.call_llm", new_callable=AsyncMock) as mock:
        mock.return_value = ("mock content", "mock reasoning", [])
        yield mock


@pytest.fixture
def mock_httpx_post():
    """Mock httpx.AsyncClient.post. Returns (client_mock, response_mock)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "result": {}}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        yield mock_client, mock_response


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test.db"
