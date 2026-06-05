from __future__ import annotations

from typing import Any

import structlog

from sai.agents.base.agent import SpatialAgent
from sai.agents.base.config import AgentConfig, ToolServerConfig
from sai.llm.client import GLMClient
from sai.llm.types import Message, MessageRole, ToolDefinition

logger = structlog.get_logger(__name__)

KNOWLEDGE_AGENT_PROMPT = """你是水利知识库管家(Knowledge Agent)。职责：语义检索、标准查询、概念解释、参数查询。

你拥有以下 MCP 工具：
- mcp-knowledge: search, get_parameter, get_standard, explain_concept

工作原则：
- 优先返回有出处（标准编号/文献引用）的知识
- 区分"标准规定"和"经验值"，明确标注来源
- 不确定的内容标注置信度，绝不编造
- 其他 Agent 随时可能调用你，保持低延迟响应
- 参数查询时同时返回典型值范围和适用条件"""


class KnowledgeAgent(SpatialAgent):
    def __init__(
        self,
        api_key: str,
        redis_url: str = "redis://localhost:6379/0",
        registry_url: str = "http://localhost:9000",
        port: int = 6005,
    ) -> None:
        config = AgentConfig(
            name="knowledge",
            port=port,
            capabilities=[
                "knowledge_search",
                "parameter_query",
                "standard_query",
                "concept_explanation",
                "semantic_search",
            ],
            tool_servers=[
                ToolServerConfig(name="mcp-knowledge", url="http://localhost:5003"),
            ],
        )
        llm = GLMClient(api_key=api_key)
        super().__init__(config=config, llm_client=llm, redis_url=redis_url, registry_url=registry_url)

    def register_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="answer_question",
                description="Answer water resource questions using knowledge base and LLM reasoning",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Question in natural language"},
                        "detail_level": {"type": "string", "enum": ["brief", "detailed", "technical"], "default": "detailed"},
                    },
                    "required": ["question"],
                },
            ),
            ToolDefinition(
                name="search",
                description="Search water resources knowledge base",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            ToolDefinition(
                name="get_parameter",
                description="Query hydraulic/hydrological parameter values",
                parameters={
                    "type": "object",
                    "properties": {
                        "parameter_name": {"type": "string"},
                        "conditions": {"type": "object"},
                    },
                    "required": ["parameter_name"],
                },
            ),
        ]

    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "answer_question":
            return await self._handle_answer_question(arguments)
        elif name == "search":
            return await self.call_tool("mcp-knowledge", "search", arguments)
        elif name == "get_parameter":
            return await self.call_tool("mcp-knowledge", "get_parameter", arguments)
        raise ValueError(f"Unknown tool: {name}")

    def get_system_prompt(self) -> str:
        return KNOWLEDGE_AGENT_PROMPT

    async def _handle_answer_question(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args["question"]
        detail_level = args.get("detail_level", "detailed")

        search_result = await self.call_tool("mcp-knowledge", "search", {"query": question, "top_k": 3})

        concept_result = await self.call_tool("mcp-knowledge", "explain_concept", {
            "concept": question,
            "detail_level": detail_level,
        })

        import json
        context_str = json.dumps({
            "search_results": search_result,
            "concept_info": concept_result,
        }, ensure_ascii=False, default=str)

        messages = [
            Message(role=MessageRole.USER, content=f"问题：{question}"),
            Message(role=MessageRole.USER, content=f"知识库检索结果：\n{context_str}"),
            Message(role=MessageRole.USER, content=f"请基于知识库信息回答，详细程度：{detail_level}。如果知识库信息不足，说明并给出你能确定的内容。"),
        ]

        response = await self.reason(messages)
        return {"answer": response.content, "sources": {"search": search_result, "concept": concept_result}}


def main():
    import os
    agent = KnowledgeAgent(
        api_key=os.environ.get("ZHIPUAI_API_KEY", ""),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        registry_url=os.environ.get("REGISTRY_URL", "http://localhost:9000"),
    )
    import asyncio
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
