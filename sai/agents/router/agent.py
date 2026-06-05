from __future__ import annotations

import json
from typing import Any

import structlog

from sai.agents.base.agent import SpatialAgent
from sai.agents.base.config import AgentConfig, ToolServerConfig
from sai.llm.client import GLMClient
from sai.llm.types import Message, MessageRole, ToolDefinition

logger = structlog.get_logger(__name__)

ROUTER_PROMPT = """你是水利空间智能体的总指挥(Router Agent)。你的职责：

1. 理解用户意图，判断任务类型和复杂度
2. 简单知识问答 → 调用 knowledge agent 的 answer_question 工具
3. 空间分析任务 → 调用 gis agent 的 analyze 任务
4. 复杂多步任务 → 制定执行计划，按顺序调度多个 agent
5. 整合各 agent 结果，用清晰的语言回复用户

专家团队：
- gis: 空间分析、几何运算、栅格处理、坐标转换
- knowledge: 水利知识检索、标准查询、概念解释、参数查询
- data: 数据管理、导入导出、格式转换、质量检查
- hydro: 水文建模、SWMM模型、设计暴雨、产汇流计算 (Phase 2)
- flood: 内涝模拟、风险评估、管网评估、预警 (Phase 2)
- report: 可视化、制图、报告生成 (Phase 2)

调度原则：
- 依赖关系的步骤串行，无依赖的并行
- 每次只调度必要的 agent，不浪费资源
- 结果要整合后用自然语言回复，不要直接返回原始 JSON"""


class RouterAgent(SpatialAgent):
    def __init__(
        self,
        api_key: str,
        redis_url: str = "redis://localhost:6379/0",
        registry_url: str = "http://localhost:9000",
        port: int = 6000,
    ) -> None:
        config = AgentConfig(
            name="router",
            port=port,
            capabilities=[
                "intent_routing",
                "task_decomposition",
                "workflow_orchestration",
                "result_synthesis",
            ],
            tool_servers=[
                ToolServerConfig(name="mcp-gis", url="http://localhost:5001"),
                ToolServerConfig(name="mcp-data", url="http://localhost:5002"),
                ToolServerConfig(name="mcp-knowledge", url="http://localhost:5003"),
                ToolServerConfig(name="mcp-map", url="http://localhost:5004"),
            ],
        )
        llm = GLMClient(api_key=api_key)
        super().__init__(config=config, llm_client=llm, redis_url=redis_url, registry_url=registry_url)

    def register_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="ask_question",
                description="Answer user questions by routing to appropriate agents and synthesizing results",
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "User's question in natural language"},
                        "context": {"type": "string", "description": "Additional context or previous conversation"},
                    },
                    "required": ["question"],
                },
            ),
            ToolDefinition(
                name="execute_analysis",
                description="Execute a multi-step spatial analysis by coordinating multiple agents",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_description": {"type": "string", "description": "Analysis task description"},
                        "steps": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"agent": {"type": "string"}, "action": {"type": "string"}, "params": {"type": "object"}}},
                            "description": "Ordered list of agent tasks to execute",
                        },
                    },
                    "required": ["task_description"],
                },
            ),
        ]

    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "ask_question":
            return await self._handle_question(arguments)
        elif name == "execute_analysis":
            return await self._handle_analysis(arguments)
        raise ValueError(f"Unknown tool: {name}")

    def get_system_prompt(self) -> str:
        return ROUTER_PROMPT

    async def _handle_question(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args["question"]
        context = args.get("context", "")

        messages = [Message(role=MessageRole.USER, content=question)]
        if context:
            messages.insert(0, Message(role=MessageRole.USER, content=f"上下文：{context}"))

        knowledge_tool_defs = [
            ToolDefinition(
                name="search_knowledge",
                description="Search water resources knowledge base",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            ),
            ToolDefinition(
                name="explain_concept",
                description="Explain a water resource concept",
                parameters={"type": "object", "properties": {"concept": {"type": "string"}}, "required": ["concept"]},
            ),
            ToolDefinition(
                name="get_parameter",
                description="Get hydraulic/hydrological parameter value",
                parameters={"type": "object", "properties": {"parameter_name": {"type": "string"}}, "required": ["parameter_name"]},
            ),
        ]

        response = await self.reason(messages, tools=knowledge_tool_defs)

        if response.tool_calls:
            results: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                try:
                    result = await self.call_tool("mcp-knowledge", tc.name, tc.arguments)
                    results.append({"tool": tc.name, "result": result})
                except Exception as e:
                    results.append({"tool": tc.name, "error": str(e)})

            tool_results_str = json.dumps(results, ensure_ascii=False, default=str)
            synthesis_messages = messages + [
                Message(role=MessageRole.ASSISTANT, content=response.content, tool_calls=response.tool_calls),
                Message(role=MessageRole.USER, content=f"检索结果：\n{tool_results_str}\n\n请基于以上信息回答用户问题。"),
            ]
            final = await self.reason(synthesis_messages)
            return {"answer": final.content, "sources": results}

        return {"answer": response.content}

    async def _handle_analysis(self, args: dict[str, Any]) -> dict[str, Any]:
        task_description = args["task_description"]
        steps = args.get("steps", [])

        if not steps:
            messages = [
                Message(role=MessageRole.USER, content=f"请为以下任务制定执行计划：\n{task_description}"),
            ]
            plan_response = await self.reason(messages)
            return {"plan": plan_response.content, "status": "plan_generated"}

        results: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            agent_name = step.get("agent", "")
            action = step.get("action", "")
            params = step.get("params", {})

            agent_to_server = {
                "gis": "mcp-gis",
                "data": "mcp-data",
                "knowledge": "mcp-knowledge",
                "map": "mcp-map",
            }

            server_name = agent_to_server.get(agent_name, f"mcp-{agent_name}")

            try:
                result = await self.call_tool(server_name, action, params)
                results.append({"step": i + 1, "agent": agent_name, "action": action, "status": "success", "result": result})
            except Exception as e:
                results.append({"step": i + 1, "agent": agent_name, "action": action, "status": "error", "error": str(e)})
                break

        return {"task": task_description, "steps_completed": len(results), "results": results}


def main():
    import os
    agent = RouterAgent(
        api_key=os.environ.get("ZHIPUAI_API_KEY", ""),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        registry_url=os.environ.get("REGISTRY_URL", "http://localhost:9000"),
    )
    import asyncio
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
