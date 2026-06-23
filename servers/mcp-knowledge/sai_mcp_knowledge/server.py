from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)

KNOWLEDGE_BASE = Path(__file__).parent.parent.parent.parent / "knowledge"
PARAM_TABLES = KNOWLEDGE_BASE / "param_tables"


async def search(query: str, top_k: int = 5, filter: dict[str, Any] | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for f in (KNOWLEDGE_BASE / "documents").rglob("*.md"):
        content = f.read_text(encoding="utf-8")
        if query.lower() in content.lower():
            results.append({
                "content": content[:2000],
                "source": str(f.relative_to(KNOWLEDGE_BASE)),
                "relevance_score": 0.8,
            })
            if len(results) >= top_k:
                break

    for f in (KNOWLEDGE_BASE / "documents").rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            text = json.dumps(data, ensure_ascii=False)
            if query.lower() in text.lower():
                results.append({
                    "content": text[:2000],
                    "source": str(f.relative_to(KNOWLEDGE_BASE)),
                    "relevance_score": 0.75,
                })
                if len(results) >= top_k:
                    break
        except json.JSONDecodeError:
            pass

    return {"query": query, "results": results, "total": len(results)}


async def get_parameter(parameter_name: str, conditions: dict[str, Any] | None = None) -> dict[str, Any]:
    if "/" in parameter_name or "\\" in parameter_name or ".." in parameter_name:
        return {"error": "Invalid parameter name"}
    param_file = PARAM_TABLES / f"{parameter_name}.json"
    if not param_file.exists():
        return {"error": f"Parameter table not found: {parameter_name}", "available": [p.stem for p in PARAM_TABLES.glob("*.json")]}

    data = json.loads(param_file.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("entries", [data])

    if conditions:
        filtered = []
        for entry in entries:
            match = all(
                str(entry.get(k, "")).lower() == str(v).lower()
                for k, v in conditions.items()
            )
            if match:
                filtered.append(entry)
        entries = filtered if filtered else entries

    return {"parameter": parameter_name, "results": entries, "conditions": conditions}


async def get_standard(standard_id: str | None = None, keyword: str | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    std_dir = KNOWLEDGE_BASE / "documents"
    if not std_dir.exists():
        return {"results": [], "note": "No standards directory found"}

    for f in std_dir.rglob("*.md"):
        content = f.read_text(encoding="utf-8")
        if standard_id and standard_id.lower() in f.name.lower():
            results.append({"content": content[:3000], "source": f.name})
        elif keyword and keyword.lower() in content.lower():
            results.append({"content": content[:3000], "source": f.name})
        if len(results) >= 10:
            break

    return {"results": results}


async def explain_concept(concept: str, detail_level: str = "detailed") -> dict[str, Any]:
    concepts_file = KNOWLEDGE_BASE / "documents" / "concepts.json"
    if concepts_file.exists():
        data = json.loads(concepts_file.read_text(encoding="utf-8"))
        if concept in data:
            return {"concept": concept, **data[concept], "detail_level": detail_level}
    return {"concept": concept, "explanation": f"Concept '{concept}' not in local knowledge base. Use LLM reasoning.", "detail_level": detail_level}


mcp_server = Server("mcp-knowledge")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Knowledge Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TOOLS = [
    Tool(name="search", description="Search water resources knowledge base", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}}, "required": ["query"]}),
    Tool(name="get_parameter", description="Query hydraulic/hydrological parameter values (manning_n, scs_cn, design_storm, etc.)", inputSchema={"type": "object", "properties": {"parameter_name": {"type": "string"}, "conditions": {"type": "object"}}, "required": ["parameter_name"]}),
    Tool(name="get_standard", description="Query water resource standards (GB/SL)", inputSchema={"type": "object", "properties": {"standard_id": {"type": "string"}, "keyword": {"type": "string"}}}),
    Tool(name="explain_concept", description="Explain a water resource concept", inputSchema={"type": "object", "properties": {"concept": {"type": "string"}, "detail_level": {"type": "string", "enum": ["brief", "detailed", "technical"], "default": "detailed"}}, "required": ["concept"]}),
]

HANDLERS = {"search": search, "get_parameter": get_parameter, "get_standard": get_standard, "explain_concept": explain_concept}


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    try:
        result = await handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-knowledge", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body["name"])
    if not handler:
        return {"error": f"Unknown tool: {body['name']}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5003)


if __name__ == "__main__":
    main()
