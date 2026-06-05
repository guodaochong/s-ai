from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sai.llm.types import (
    CompletionConfig,
    LLMResponse,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
    ToolResult,
)

logger = structlog.get_logger(__name__)

API_BASE = "https://open.bigmodel.cn/api/paas/v4"
COMPLETIONS_ENDPOINT = f"{API_BASE}/chat/completions"


def _message_to_dict(msg: Message) -> dict[str, Any]:
    d: dict[str, Any] = {"role": msg.role.value}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.name is not None:
        d["name"] = msg.name
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    if msg.tool_calls is not None:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in msg.tool_calls
        ]
    return d


def _parse_response(data: dict[str, Any]) -> LLMResponse:
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    tool_calls: list[ToolCall] = []
    for tc in message.get("tool_calls", []):
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {"_raw": args_str}
        tool_calls.append(ToolCall(id=tc["id"], name=fn.get("name", ""), arguments=args))

    return LLMResponse(
        content=message.get("content"),
        tool_calls=tool_calls,
        usage=data.get("usage", {}),
        finish_reason=choice.get("finish_reason", ""),
    )


class GLMClient:
    def __init__(self, api_key: str, default_model: str = "glm-5.1") -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: CompletionConfig | None = None,
    ) -> LLMResponse:
        cfg = config or CompletionConfig()
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "top_p": cfg.top_p,
        }
        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]

        logger.debug(
            "llm_request",
            model=cfg.model,
            messages=len(messages),
            tools=len(tools) if tools else 0,
        )

        resp = await self._http.post(
            COMPLETIONS_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        logger.debug(
            "llm_response",
            finish_reason=data.get("choices", [{}])[0].get("finish_reason"),
            usage=data.get("usage"),
        )

        return _parse_response(data)

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: CompletionConfig | None = None,
    ) -> AsyncGenerator[LLMResponse, None]:
        cfg = config or CompletionConfig()
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]

        async with self._http.stream(
            "POST",
            COMPLETIONS_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    yield _parse_response(chunk)
                except json.JSONDecodeError:
                    continue

    async def structured_output(
        self,
        messages: list[Message],
        schema: type[BaseModel],
        config: CompletionConfig | None = None,
    ) -> BaseModel:
        schema_json = schema.model_json_schema()
        enriched = messages + [
            Message(
                role=MessageRole.USER,
                content=(
                    f"Respond with valid JSON matching this schema. "
                    f"Do NOT wrap in markdown code blocks.\n"
                    f"Schema: {json.dumps(schema_json, ensure_ascii=False)}"
                ),
            )
        ]
        response = await self.chat(enriched, config=config)
        content = response.content or ""
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return schema.model_validate_json(content)

    @staticmethod
    def build_system_prompt(
        role_desc: str,
        capabilities: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> str:
        parts = [role_desc]
        if capabilities:
            parts.append("\n你拥有以下能力：")
            for cap in capabilities:
                parts.append(f"- {cap}")
        if constraints:
            parts.append("\n工作原则：")
            for c in constraints:
                parts.append(f"- {c}")
        return "\n".join(parts)

    @staticmethod
    def format_tool_results(results: list[ToolResult]) -> list[Message]:
        return [
            Message(
                role=MessageRole.TOOL,
                content=r.content,
                tool_call_id=r.tool_call_id,
                name=f"tool_error_{r.tool_call_id}" if r.is_error else f"tool_{r.tool_call_id}",
            )
            for r in results
        ]
