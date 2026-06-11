from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

import structlog

from app.config import logger


@dataclass
class TraceSpan:
    trace_id: str
    query: str
    t_start: float
    events: list = field(default_factory=list)

    def add(self, name: str, detail: str = "", duration_ms: float = 0):
        self.events.append({"name": name, "ts": time.time(), "detail": detail, "duration_ms": int(duration_ms)})

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "query": self.query, "duration_ms": int((time.time() - self.t_start) * 1000), "events": self.events}


_traces: OrderedDict[str, TraceSpan] = OrderedDict()
_trace_counter = 0


def new_trace(query: str) -> TraceSpan:
    global _trace_counter
    _trace_counter += 1
    span = TraceSpan(trace_id=f"tr_{_trace_counter:06d}", query=query, t_start=time.time())
    _traces[span.trace_id] = span
    while len(_traces) > 100:
        _traces.popitem(last=False)
    return span


def get_all_traces() -> list[dict]:
    return [t.to_dict() for t in reversed(_traces.values())]


def get_trace(trace_id: str) -> dict | None:
    t = _traces.get(trace_id)
    return t.to_dict() if t else None


class DigitalTwinBridge:
    def __init__(self):
        self.sources: dict[str, dict] = {}

    def register(self, name: str, src_type: str, config: dict):
        self.sources[name] = {"type": src_type, **config, "registered_at": time.time()}

    def list_sources(self) -> list[dict]:
        return [{"name": k, **v} for k, v in self.sources.items()]

    async def health_check(self) -> dict[str, str]:
        results = {}
        for name in self.sources:
            results[name] = "healthy" if self.sources[name]["type"] in ("file", "api") else "unknown"
        return results


twin = DigitalTwinBridge()


_evolution_log: list[dict] = []
_evolution_counter = 0


def log_routing(query: str, layer: str, tool: str, was_correct: bool):
    global _evolution_counter
    _evolution_counter += 1
    _evolution_log.append({"query": query[:100], "layer": layer, "tool": tool, "correct": was_correct, "ts": time.time()})
    if len(_evolution_log) > 1000:
        _evolution_log[:] = _evolution_log[-500:]


def evolution_stats() -> dict:
    if not _evolution_log:
        return {"total": 0, "accuracy": 0}
    total = len(_evolution_log)
    correct = sum(1 for e in _evolution_log if e["correct"])
    by_layer: dict[str, dict] = {}
    for e in _evolution_log:
        l = e["layer"]
        if l not in by_layer:
            by_layer[l] = {"total": 0, "correct": 0}
        by_layer[l]["total"] += 1
        by_layer[l]["correct"] += 1 if e["correct"] else 0
    return {"total": total, "accuracy": round(correct / total, 3), "by_layer": by_layer}


def evolution_suggestions() -> list[str]:
    suggestions = []
    l3_entries = [e for e in _evolution_log if e["layer"] == "L3"]
    if len(l3_entries) >= 5:
        for e in l3_entries[-10:]:
            if e["correct"]:
                suggestions.append(f"建议新增规则: \"{e['query'][:20]}\" → {e['tool']}")
    return suggestions[:5]
