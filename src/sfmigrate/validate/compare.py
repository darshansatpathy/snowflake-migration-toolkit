"""Compare one table between two databases: schema, counts, aggregates, then every row.

Rows are streamed from both sides in key order and merged, so memory stays flat whatever the
table size. If one side's order disagrees with ours (a collation the adapter could not pin), the
comparison falls back to holding that table's keys in memory and says so in the report.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from sfmigrate.validate import normalize
from sfmigrate.validate.adapters import Adapter, Column, connect
from sfmigrate.validate.normalize import Rules

FAMILIES = [
    ("boolean", re.compile(r"^bool")),
    ("integer", re.compile(r"int|^number\(\d+(,\s*0)?\)$|^serial")),
    ("decimal", re.compile(r"numeric|decimal|number|money")),
    ("float", re.compile(r"float|double|real|binary_double")),
    ("timestamp", re.compile(r"timestamp|datetime")),
    ("date", re.compile(r"^date$")),
    ("time", re.compile(r"^time")),
    ("binary", re.compile(r"blob|bytea|binary|raw|varbinary")),
    ("string", re.compile(r"char|text|string|clob|varchar")),
]
WIDENING = {
    ("integer", "decimal"),
    ("date", "timestamp"),
    ("float", "decimal"),
    ("decimal", "float"),
    ("integer", "float"),
}


def family(column: Column) -> str:
    t = column.type.lower()
    if t in ("decimal", "numeric", "number") and column.scale == 0 and column.precision:
        return "integer"
    for name, pattern in FAMILIES:
        if pattern.search(t):
            return name
    return t


class TableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    target: str
    key: list[str] = Field(min_length=1)
    exclude: list[str] = []
    rename: dict[str, str] = Field(default_factory=dict, description="source column -> target column")
    where: str | None = None
    rules: dict[str, Any] = Field(default_factory=dict)
    source_rules: dict[str, Any] = Field(default_factory=dict)
    target_rules: dict[str, Any] = Field(default_factory=dict)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    rules: Rules = Rules()
    sample: int = Field(default=10, ge=0, le=1000)
    tables: list[TableSpec] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> Config:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "severity": self.severity, "detail": self.detail}


@dataclass
class TableReport:
    table: str
    checks: list[Check] = field(default_factory=list)
    missing: list[tuple[Any, ...]] = field(default_factory=list)
    extra: list[tuple[Any, ...]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    fallback: str = ""

    @property
    def ok(self) -> bool:
        return all(c.ok or c.severity == "warning" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "counts": self.counts,
            "missing_sample": [list(k) for k in self.missing],
            "extra_sample": [list(k) for k in self.extra],
            "changed_sample": self.changed,
            "seconds": round(self.seconds, 3),
            "fallback": self.fallback,
        }


def _columns(spec: TableSpec, src: list[Column], tgt: list[Column], report: TableReport) -> list[tuple[Column, Column]]:
    by_name = {c.name.lower(): c for c in tgt}
    pairs = []
    excluded = {e.lower() for e in spec.exclude}
    for s in src:
        if s.name.lower() in excluded:
            continue
        target_name = spec.rename.get(s.name, spec.rename.get(s.name.lower(), s.name)).lower()
        t = by_name.pop(target_name, None)
        if t is None:
            report.checks.append(Check(f"column {s.name}", False, "missing in target"))
            continue
        pairs.append((s, t))
        fs, ft = family(s), family(t)
        if fs != ft and (fs, ft) not in WIDENING:
            report.checks.append(Check(f"type {s.name}", False, f"{s.type} ({fs}) became {t.type} ({ft})"))
        elif fs == ft == "decimal" and (s.scale or 0) > (t.scale or 0):
            report.checks.append(Check(f"type {s.name}", False, f"scale {s.scale} became {t.scale}: digits are lost"))
        elif fs == ft == "string" and s.length and t.length and t.length < s.length:
            report.checks.append(Check(f"type {s.name}", False, f"length {s.length} became {t.length}: values may not fit"))
        elif (fs, ft) in WIDENING:
            report.checks.append(Check(f"type {s.name}", True, f"{s.type} widened to {t.type}", "warning"))
        if not s.nullable and t.nullable:
            report.checks.append(Check(f"nullability {s.name}", True, "NOT NULL not carried over", "warning"))
    for extra in by_name.values():
        if extra.name.lower() not in excluded:
            report.checks.append(Check(f"column {extra.name}", True, "only in target", "warning"))
    return pairs


def _stream(
    adapter: Adapter,
    table: str,
    cols: list[str],
    keys: list[str],
    text_keys: set[str],
    where: str | None,
    rules: Rules,
    nkeys: int,
) -> Iterator[tuple[tuple[Any, ...], tuple[Any, ...]]]:
    for row in adapter.rows(table, cols, keys, text_keys, where):
        values = tuple(normalize.value(v, rules) for v in row)
        yield values[:nkeys], values[nkeys:]


def compare_table(source: Adapter, target: Adapter, spec: TableSpec, base: Rules, sample: int = 10) -> TableReport:
    started = time.monotonic()
    report = TableReport(spec.name)
    s_rules = base.merged({**spec.rules, **spec.source_rules})
    t_rules = base.merged({**spec.rules, **spec.target_rules})
    src_cols, tgt_cols = source.columns(spec.source), target.columns(spec.target)
    if not src_cols or not tgt_cols:
        report.checks.append(Check("table", False, f"not found: {spec.source if not src_cols else spec.target}"))
        return report
    pairs = _columns(spec, src_cols, tgt_cols, report)
    names = {s.name.lower(): (s, t) for s, t in pairs}
    missing_keys = [k for k in spec.key if k.lower() not in names]
    if missing_keys:
        report.checks.append(Check("key", False, f"key columns not comparable: {missing_keys}"))
        return report

    s_count, t_count = source.count(spec.source, spec.where), target.count(spec.target, spec.where)
    report.counts = {"source": s_count, "target": t_count}
    report.checks.append(Check("row count", s_count == t_count, f"source {s_count}, target {t_count}"))

    for s, t in pairs:
        fam = family(s)
        if fam not in ("integer", "decimal", "float", "date", "timestamp"):
            continue
        numeric = fam in ("integer", "decimal", "float")
        a = source.aggregates(spec.source, s.name, numeric, spec.where)
        b = target.aggregates(spec.target, t.name, numeric, spec.where)
        diffs = [
            k
            for k in a
            if not normalize.equal(
                normalize.value(a[k], s_rules),
                normalize.value(b[k], t_rules),
                s_rules.model_copy(update={"numeric_tolerance": s_rules.numeric_tolerance * max(1, s_count)}),
            )
        ]
        if diffs:
            report.checks.append(Check(f"aggregates {s.name}", False, "; ".join(f"{k}: {a[k]} vs {b[k]}" for k in diffs)))

    key_pairs = [names[k.lower()] for k in spec.key]
    value_pairs = [p for p in pairs if p not in key_pairs]
    s_names = [p[0].name for p in key_pairs + value_pairs]
    t_names = [p[1].name for p in key_pairs + value_pairs]
    text_keys_s = {p[0].name for p in key_pairs if family(p[0]) == "string"}
    text_keys_t = {p[1].name for p in key_pairs if family(p[1]) == "string"}
    nk = len(key_pairs)
    left = _stream(source, spec.source, s_names, [p[0].name for p in key_pairs], text_keys_s, spec.where, s_rules, nk)
    right = _stream(target, spec.target, t_names, [p[1].name for p in key_pairs], text_keys_t, spec.where, t_rules, nk)
    counts = {"missing": 0, "extra": 0, "changed": 0, "duplicate_keys": 0, "compared": 0}
    value_names = [p[0].name for p in value_pairs]
    try:
        _merge(left, right, value_names, s_rules, counts, report, sample)
    except _OrderMismatch as exc:
        report.fallback = f"key order differs between engines ({exc}); compared with keys held in memory"
        counts = {"missing": 0, "extra": 0, "changed": 0, "duplicate_keys": 0, "compared": 0}
        report.missing, report.extra, report.changed = [], [], []
        left = _stream(source, spec.source, s_names, [p[0].name for p in key_pairs], text_keys_s, spec.where, s_rules, nk)
        right = _stream(target, spec.target, t_names, [p[1].name for p in key_pairs], text_keys_t, spec.where, t_rules, nk)
        _hash_join(left, right, value_names, s_rules, counts, report, sample)
    report.counts.update(counts)
    report.checks.append(
        Check(
            "rows",
            not (counts["missing"] or counts["extra"] or counts["changed"] or counts["duplicate_keys"]),
            f"{counts['compared']} compared: {counts['missing']} missing, {counts['extra']} extra, "
            f"{counts['changed']} changed, {counts['duplicate_keys']} duplicate keys",
        )
    )
    report.seconds = time.monotonic() - started
    return report


class _OrderMismatch(Exception):
    pass


def _ordered(stream: Iterator[tuple[tuple[Any, ...], tuple[Any, ...]]], side: str) -> Iterator[tuple[tuple[Any, ...], tuple[Any, ...]]]:
    previous = None
    for k, v in stream:
        sk = normalize.key(k)
        if previous is not None and sk < previous:
            raise _OrderMismatch(f"{side} returned {k} after a larger key")
        previous = sk
        yield k, v


def _diff(
    k: tuple[Any, ...],
    a: tuple[Any, ...],
    b: tuple[Any, ...],
    names: list[str],
    rules: Rules,
    counts: dict[str, int],
    report: TableReport,
    sample: int,
) -> None:
    counts["compared"] += 1
    cols = {n: {"source": x, "target": y} for n, x, y in zip(names, a, b, strict=True) if not normalize.equal(x, y, rules)}
    if cols:
        counts["changed"] += 1
        if len(report.changed) < sample:
            report.changed.append({"key": [str(x) for x in k], "columns": {n: {s: str(v) for s, v in d.items()} for n, d in cols.items()}})


def _merge(
    left: Iterator[Any],
    right: Iterator[Any],
    names: list[str],
    rules: Rules,
    counts: dict[str, int],
    report: TableReport,
    sample: int,
) -> None:
    lit, rit = _ordered(left, "source"), _ordered(right, "target")
    a, b = next(lit, None), next(rit, None)
    last_a = last_b = None
    while a is not None or b is not None:
        if a is not None and a[0] == last_a:
            counts["duplicate_keys"] += 1
            a = next(lit, None)
            continue
        if b is not None and b[0] == last_b:
            counts["duplicate_keys"] += 1
            b = next(rit, None)
            continue
        if b is None or (a is not None and normalize.key(a[0]) < normalize.key(b[0])):
            assert a is not None
            counts["missing"] += 1
            if len(report.missing) < sample:
                report.missing.append(a[0])
            last_a = a[0]
            a = next(lit, None)
        elif a is None or normalize.key(b[0]) < normalize.key(a[0]):
            counts["extra"] += 1
            if len(report.extra) < sample:
                report.extra.append(b[0])
            last_b = b[0]
            b = next(rit, None)
        else:
            _diff(a[0], a[1], b[1], names, rules, counts, report, sample)
            last_a, last_b = a[0], b[0]
            a, b = next(lit, None), next(rit, None)


def _hash_join(
    left: Iterator[Any],
    right: Iterator[Any],
    names: list[str],
    rules: Rules,
    counts: dict[str, int],
    report: TableReport,
    sample: int,
) -> None:
    held: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for k, v in left:
        if k in held:
            counts["duplicate_keys"] += 1
            continue
        held[k] = v
    seen: set[tuple[Any, ...]] = set()
    for k, v in right:
        if k in seen:
            counts["duplicate_keys"] += 1
            continue
        seen.add(k)
        if k not in held:
            counts["extra"] += 1
            if len(report.extra) < sample:
                report.extra.append(k)
            continue
        _diff(k, held.pop(k), v, names, rules, counts, report, sample)
    for k in held:
        counts["missing"] += 1
        if len(report.missing) < sample:
            report.missing.append(k)


@dataclass
class Report:
    tables: list[TableReport]

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "tables": [t.to_dict() for t in self.tables]}

    def markdown(self) -> str:
        lines = [
            "# Validation report",
            "",
            f"**{'PASS' if self.ok else 'FAIL'}**: {len(self.tables)} table(s)",
            "",
            "| Table | Result | Rows compared | Missing | Extra | Changed | Seconds |",
            "|---|---|---|---|---|---|---|",
        ]
        for t in self.tables:
            c = t.counts
            lines.append(
                f"| {t.table} | {'pass' if t.ok else '**fail**'} | {c.get('compared', 0)} | "
                f"{c.get('missing', 0)} | {c.get('extra', 0)} | {c.get('changed', 0)} | {t.seconds:.2f} |"
            )
        for t in self.tables:
            failed = [c for c in t.checks if not c.ok or c.severity == "warning"]
            if not failed and not t.changed and not t.fallback:
                continue
            lines += ["", f"## {t.table}", ""]
            lines += [f"- {'warning' if c.ok else 'error'}: {c.name}: {c.detail}" for c in failed]
            if t.fallback:
                lines.append(f"- note: {t.fallback}")
            if t.missing:
                lines.append(f"- missing in target (sample): {', '.join(str(list(k)) for k in t.missing)}")
            if t.extra:
                lines.append(f"- only in target (sample): {', '.join(str(list(k)) for k in t.extra)}")
            for ch in t.changed:
                cols = "; ".join(f"{n}: {d['source']!r} vs {d['target']!r}" for n, d in ch["columns"].items())
                lines.append(f"- changed {ch['key']}: {cols}")
        return "\n".join(lines) + "\n"


def run(config: Config) -> Report:
    source, target = connect(config.source), connect(config.target)
    try:
        return Report([compare_table(source, target, spec, config.rules, config.sample) for spec in config.tables])
    finally:
        source.close()
        target.close()
