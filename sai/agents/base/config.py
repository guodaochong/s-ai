from __future__ import annotations

from pydantic import BaseModel


class ToolServerConfig(BaseModel):
    name: str
    url: str
    reconnect_interval: int = 5


class AgentConfig(BaseModel):
    name: str
    host: str = "0.0.0.0"
    port: int = 6000
    capabilities: list[str] = []
    tool_servers: list[ToolServerConfig] = []
    system_prompt_path: str | None = None
    max_concurrent_tasks: int = 5
    health_check_interval: int = 30
