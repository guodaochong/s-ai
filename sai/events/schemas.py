from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    AGENT_COLLAB = "agent_collab"
    HUMAN_INPUT = "human_input"
    HUMAN_APPROVED = "human_approved"
    ERROR = "error"
    DATA_PRODUCED = "data_produced"
    DATA_CONSUMED = "data_consumed"


class TrustLevel(str, Enum):
    AUTO = "auto"
    NOTIFY = "notify"
    CONFIRM = "confirm"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class AgentEvent:
    event_type: EventType
    agent: str
    action: str
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    parent_event_id: str | None = None
    human_approved: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent,
            "action": self.action,
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "parent_event_id": self.parent_event_id,
            "human_approved": self.human_approved,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentEvent:
        data = {**data}
        data["event_type"] = EventType(data["event_type"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class EventFilter:
    event_types: list[EventType] | None = None
    agent: str | None = None
    action: str | None = None
    parent_event_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100


@dataclass(frozen=True)
class BlackboardEntry:
    key: str
    value: Any
    producer_agent: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int | None = None
    version: int = 1
