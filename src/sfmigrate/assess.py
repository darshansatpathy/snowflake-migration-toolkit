"""Assessment: what a codebase contains, how much translates on its own, and what is left.

Effort is a planning estimate with explicit weights (hours per statement by status), not a
promise; the weights are the first thing a team should calibrate after a pilot.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sfmigrate.rules import CATALOG
from sfmigrate.translator import FileResult, detect_dialect, translate_text

HOURS = {"auto": 0.05, "dropped": 0.0, "assisted": 0.5, "manual": 4.0}
SUFFIXES = (".sql", ".bteq", ".btq", ".pls", ".pks", ".pkb", ".ddl")


@dataclass
class Assessment:
    files: list[FileResult] = field(default_factory=list)
    hours: dict[str, float] = field(default_factory=lambda: dict(HOURS))

    @property
    def statements(self) -> int:
        return sum(len(f.translations) for f in self.files)

    def by_status(self) -> Counter[str]:
        return Counter(t.status for f in self.files for t in f.translations)

    def by_rule(self) -> Counter[str]:
        return Counter(n.rule for f in self.files for t in f.translations for n in t.notes)

    def by_kind(self) -> Counter[str]:
        return Counter(t.kind for f in self.files for t in f.translations)

    def effort_hours(self) -> float:
        return round(sum(self.hours[t.status] for f in self.files for t in f.translations), 1)

    def automation_rate(self) -> float:
        counts = self.by_status()
        total = sum(counts.values()) - counts["dropped"]
        return (counts["auto"] + counts["assisted"]) / total if total else 1.0

    def manual_items(self) -> list[dict[str, Any]]:
        items = []
        for f in self.files:
            for line, t in zip(f.lines, f.translations, strict=True):
                if t.status == "manual":
                    reason = next(n.message for n in t.notes if n.severity == "manual")
                    items.append(
                        {
                            "file": f.path,
                            "line": line,
                            "kind": t.kind,
                            "reason": reason,
                            "source": t.source.splitlines()[0][:100],
                        }
                    )
        return items

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": len(self.files),
            "statements": self.statements,
            "status": dict(self.by_status()),
            "automation_rate": round(self.automation_rate(), 3),
            "effort_hours": self.effort_hours(),
            "hours_per_statement": self.hours,
            "rules": dict(self.by_rule()),
            "kinds": dict(self.by_kind()),
            "manual": self.manual_items(),
        }

    def markdown(self) -> str:
        status = self.by_status()
        titles = {r.id: r.title for r in CATALOG}
        lines = [
            "# Migration assessment",
            "",
            f"{len(self.files)} files, {self.statements} statements. "
            f"**{self.automation_rate():.0%}** translate without a rewrite "
            f"({status['auto']} automatic, {status['assisted']} needing review); "
            f"{status['manual']} need a person; {status['dropped']} are dropped on purpose.",
            "",
            f"Estimated effort: **{self.effort_hours()} hours** "
            f"(auto {self.hours['auto']}h, assisted {self.hours['assisted']}h, manual {self.hours['manual']}h "
            "per statement; calibrate after a pilot).",
            "",
            "| File | Dialect | Statements | Auto | Assisted | Manual | Dropped |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in self.files:
            c = Counter(t.status for t in f.translations)
            lines.append(f"| {f.path} | {f.dialect} | {len(f.translations)} | {c['auto']} | {c['assisted']} | {c['manual']} | {c['dropped']} |")
        lines += ["", "## What the rules found", "", "| Rule | What | Statements |", "|---|---|---|"]
        for rule, count in sorted(self.by_rule().items()):
            lines.append(f"| {rule} | {titles.get(rule, rule.title())} | {count} |")
        manual = self.manual_items()
        if manual:
            lines += ["", "## Needs a person", "", "| Where | What | Why |", "|---|---|---|"]
            for m in manual:
                lines.append(f"| {m['file']}:{m['line']} | {m['kind']} | {m['reason']} |")
        return "\n".join(lines) + "\n"

    def csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["file", "line", "dialect", "kind", "name", "status", "rules", "notes"])
        for f in self.files:
            for line, t in zip(f.lines, f.translations, strict=True):
                writer.writerow(
                    [
                        f.path,
                        line,
                        t.dialect,
                        t.kind,
                        t.name,
                        t.status,
                        " ".join(t.rules),
                        " | ".join(n.message for n in t.notes),
                    ]
                )
        return buffer.getvalue()


def sql_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES)


def assess(root: Path, dialect: str | None = None, hours: dict[str, float] | None = None) -> Assessment:
    result = Assessment(hours={**HOURS, **(hours or {})})
    for path in sql_files(root):
        rel = str(path.relative_to(root)) if root.is_dir() else path.name
        text = path.read_text(encoding="utf-8", errors="replace")
        result.files.append(translate_text(text, detect_dialect(path, dialect), rel))
    return result


def write_translations(assessment: Assessment, out: Path) -> list[Path]:
    written = []
    for f in assessment.files:
        target = out / Path(f.path).with_suffix(".snowflake.sql")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.script(), encoding="utf-8")
        written.append(target)
    (out / "assessment.md").write_text(assessment.markdown(), encoding="utf-8")
    (out / "assessment.json").write_text(json.dumps(assessment.to_dict(), indent=2), encoding="utf-8")
    (out / "statements.csv").write_text(assessment.csv(), encoding="utf-8")
    return written
