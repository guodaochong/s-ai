from __future__ import annotations

import time
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)


class AgentState(str, Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


_VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.INITIALIZING: {AgentState.READY, AgentState.ERROR, AgentState.STOPPING},
    AgentState.READY: {AgentState.BUSY, AgentState.DEGRADED, AgentState.STOPPING, AgentState.ERROR},
    AgentState.BUSY: {AgentState.READY, AgentState.DEGRADED, AgentState.STOPPING, AgentState.ERROR},
    AgentState.DEGRADED: {AgentState.READY, AgentState.BUSY, AgentState.STOPPING, AgentState.ERROR},
    AgentState.STOPPING: {AgentState.STOPPED},
    AgentState.STOPPED: set(),
    AgentState.ERROR: {AgentState.INITIALIZING, AgentState.STOPPING},
}


@dataclass
class AgentStatus:
    state: AgentState = AgentState.INITIALIZING
    agent_name: str = ""
    started_at: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_load: float = 0.0
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at


class LifecycleManager:
    def __init__(self, agent_name: str, max_concurrent_tasks: int = 5) -> None:
        self._max_concurrent = max_concurrent_tasks
        self._status = AgentStatus(agent_name=agent_name)

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def state(self) -> AgentState:
        return self._status.state

    def transition(self, new_state: AgentState) -> None:
        allowed = _VALID_TRANSITIONS.get(self._status.state, set())
        if new_state not in allowed:
            logger.error(
                "invalid_state_transition",
                agent=self._status.agent_name,
                from_state=self._status.state.value,
                to_state=new_state.value,
            )
            raise ValueError(
                f"Cannot transition from {self._status.state.value} to {new_state.value}"
            )
        old = self._status.state
        self._status.state = new_state
        logger.info(
            "state_transition",
            agent=self._status.agent_name,
            from_state=old.value,
            to_state=new_state.value,
        )

    def should_accept_task(self) -> bool:
        return self._status.state in {AgentState.READY, AgentState.BUSY} and \
               self._status.current_load < self._max_concurrent

    def record_task_start(self) -> None:
        self._status.current_load += 1
        if self._status.state == AgentState.READY:
            self.transition(AgentState.BUSY)

    def record_task_complete(self) -> None:
        self._status.tasks_completed += 1
        self._status.current_load = max(0, self._status.current_load - 1)
        if self._status.current_load == 0 and self._status.state == AgentState.BUSY:
            self.transition(AgentState.READY)

    def record_task_failure(self) -> None:
        self._status.tasks_failed += 1
        self._status.current_load = max(0, self._status.current_load - 1)
        if self._status.current_load == 0 and self._status.state == AgentState.BUSY:
            self.transition(AgentState.READY)

    def heartbeat(self) -> None:
        self._status.last_heartbeat = datetime.utcnow()
