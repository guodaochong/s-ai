from __future__ import annotations

from typing import Any

import structlog

from sai.agents.base.agent import SpatialAgent
from sai.agents.base.config import AgentConfig, ToolServerConfig
from sai.llm.client import GLMClient
from sai.llm.types import Message, MessageRole, ToolDefinition

logger = structlog.get_logger(__name__)

GIS_AGENT_PROMPT = """你是空间分析专家(GIS Agent)。专长：几何运算、空间查询、栅格分析、坐标系转换。

你拥有以下 MCP 工具服务器：
- mcp-gis: spatial_query, buffer, overlay, coordinate_transform, geometry_properties, read_vector, write_vector
- mcp-data: import_data, query_spatial, query_by_geometry, validate_data, list_tables

工作原则：
- 所有几何运算前先检查/统一坐标系（默认 CGCS2000 / EPSG:4490）
- 空间分析结果用 GeoJSON 格式传递
- 返回结果附带 CRS 信息和数据量统计
- 栅格操作前检查分辨率和范围对齐
- 数据读写操作通过 mcp-data 完成"""


class GISAgent(SpatialAgent):
    def __init__(
        self,
        api_key: str,
        redis_url: str = "redis://localhost:6379/0",
        registry_url: str = "http://localhost:9000",
        port: int = 6001,
    ) -> None:
        config = AgentConfig(
            name="gis",
            port=port,
            capabilities=[
                "spatial_analysis",
                "buffer_analysis",
                "overlay_analysis",
                "coordinate_transform",
                "vector_io",
                "geometry_computation",
            ],
            tool_servers=[
                ToolServerConfig(name="mcp-gis", url="http://localhost:5001"),
                ToolServerConfig(name="mcp-data", url="http://localhost:5002"),
            ],
        )
        llm = GLMClient(api_key=api_key)
        super().__init__(config=config, llm_client=llm, redis_url=redis_url, registry_url=registry_url)

    def register_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="analyze",
                description="Perform spatial analysis based on natural language description",
                parameters={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Analysis task in natural language"},
                        "geometry": {"type": "object", "description": "Input geometry (GeoJSON)"},
                        "parameters": {"type": "object", "description": "Additional parameters"},
                    },
                    "required": ["task"],
                },
            ),
            ToolDefinition(
                name="spatial_query",
                description="Query spatial relationship between geometries",
                parameters={
                    "type": "object",
                    "properties": {
                        "geometry_a": {"type": "object"},
                        "geometry_b": {"type": "object"},
                        "relation": {"type": "string", "default": "intersects"},
                    },
                    "required": ["geometry_a", "geometry_b"],
                },
            ),
            ToolDefinition(
                name="buffer_zone",
                description="Create buffer zone around geometry",
                parameters={
                    "type": "object",
                    "properties": {
                        "geometry": {"type": "object"},
                        "distance": {"type": "number", "default": 100},
                        "unit": {"type": "string", "default": "meters"},
                    },
                    "required": ["geometry"],
                },
            ),
        ]

    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "analyze":
            return await self._handle_analyze(arguments)
        elif name == "spatial_query":
            return await self.call_tool("mcp-gis", "spatial_query", arguments)
        elif name == "buffer_zone":
            return await self.call_tool("mcp-gis", "buffer", arguments)
        raise ValueError(f"Unknown tool: {name}")

    def get_system_prompt(self) -> str:
        return GIS_AGENT_PROMPT

    async def _handle_analyze(self, args: dict[str, Any]) -> dict[str, Any]:
        task = args["task"]
        geometry = args.get("geometry")
        parameters = args.get("parameters", {})

        gis_tools = [
            ToolDefinition(name="spatial_query", description="Query spatial relationships", parameters={"type": "object", "properties": {"geometry_a": {"type": "object"}, "geometry_b": {"type": "object"}, "relation": {"type": "string"}}, "required": ["geometry_a", "geometry_b"]}),
            ToolDefinition(name="buffer", description="Create buffer zone", parameters={"type": "object", "properties": {"geometry": {"type": "object"}, "distance": {"type": "number"}}, "required": ["geometry"]}),
            ToolDefinition(name="overlay", description="Geometric overlay", parameters={"type": "object", "properties": {"geometry_a": {"type": "object"}, "geometry_b": {"type": "object"}, "operation": {"type": "string"}}, "required": ["geometry_a", "geometry_b"]}),
            ToolDefinition(name="geometry_properties", description="Get geometry properties", parameters={"type": "object", "properties": {"geometry": {"type": "object"}}, "required": ["geometry"]}),
            ToolDefinition(name="coordinate_transform", description="Transform CRS", parameters={"type": "object", "properties": {"geometry": {"type": "object"}, "source_crs": {"type": "string"}, "target_crs": {"type": "string"}}, "required": ["geometry"]}),
        ]

        messages = [Message(role=MessageRole.USER, content=task)]
        if geometry:
            messages.append(Message(role=MessageRole.USER, content=f"输入几何数据：{geometry}"))
        if parameters:
            messages.append(Message(role=MessageRole.USER, content=f"参数：{parameters}"))

        response = await self.reason(messages, tools=gis_tools)

        if response.tool_calls:
            tool_results: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                try:
                    result = await self.call_tool("mcp-gis", tc.name, tc.arguments)
                    tool_results.append({"tool": tc.name, "result": result})
                except Exception as e:
                    tool_results.append({"tool": tc.name, "error": str(e)})

            import json
            summary_messages = messages + [
                Message(role=MessageRole.ASSISTANT, content=response.content, tool_calls=response.tool_calls),
                Message(role=MessageRole.USER, content=f"工具执行结果：\n{json.dumps(tool_results, ensure_ascii=False, default=str)}\n\n请总结分析结果。"),
            ]
            final = await self.reason(summary_messages)
            return {"analysis": final.content, "tool_results": tool_results}

        return {"analysis": response.content}


def main():
    import os
    agent = GISAgent(
        api_key=os.environ.get("ZHIPUAI_API_KEY", ""),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        registry_url=os.environ.get("REGISTRY_URL", "http://localhost:9000"),
    )
    import asyncio
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
