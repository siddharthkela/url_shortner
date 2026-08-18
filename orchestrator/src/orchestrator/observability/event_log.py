"""Append-only JSONL audit trail. Every scheduler event (node lifecycle,
retries, rollbacks, approvals, policy checks, replans) lands here with a
timestamp — this is the "audit-grade observability and traceability" the
assignment asks for: nothing the engine does is only visible in memory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from orchestrator.engine.dag import EventSink


@dataclass
class JsonlEventSink(EventSink):
    """Writes each emitted event as one JSON line. Also keeps an in-memory
    copy (`events`) so a run can inspect/summarize its own log without a
    round-trip through the filesystem.
    """

    path: Path
    events: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **fields: Any) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **fields,
        }
        self.events.append(event)
        with self.path.open("a") as f:
            f.write(json.dumps(event) + "\n")


def read_events(path: Path) -> List[Dict[str, Any]]:
    events = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
