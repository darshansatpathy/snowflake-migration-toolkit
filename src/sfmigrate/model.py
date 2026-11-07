"""What a translation produces: the Snowflake SQL, a status, and every note a reviewer needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["info", "warning", "manual"]
Status = Literal["auto", "assisted", "manual", "dropped"]


@dataclass(frozen=True)
class Note:
    rule: str
    severity: Severity
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "severity": self.severity, "message": self.message}


@dataclass
class Translation:
    dialect: str
    source: str
    output: str = ""
    notes: list[Note] = field(default_factory=list)
    kind: str = "statement"
    name: str = ""
    dropped: bool = False

    @property
    def status(self) -> Status:
        if any(n.severity == "manual" for n in self.notes):
            return "manual"
        if any(n.severity == "warning" for n in self.notes):
            return "assisted"
        if self.dropped:
            return "dropped"
        return "auto"

    @property
    def rules(self) -> list[str]:
        return sorted({n.rule for n in self.notes})

    def note(self, rule: str, severity: Severity, message: str) -> None:
        if not any(n.rule == rule and n.message == message for n in self.notes):
            self.notes.append(Note(rule, severity, message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dialect": self.dialect,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "source": self.source,
            "output": self.output,
            "notes": [n.to_dict() for n in self.notes],
        }
