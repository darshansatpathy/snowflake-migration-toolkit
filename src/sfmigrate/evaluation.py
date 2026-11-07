"""The evaluation gate: the translation corpus, and the validator against injected defects.

Translation: every corpus case must produce exactly its reviewed Snowflake SQL, status and
rules, and every output must parse as Snowflake.

Validation: a source table is created in PostgreSQL and copied into DuckDB the way a
real migration would copy it: CHAR padding trimmed, Oracle-style NULLs written as '', local
timestamps converted to UTC. Each scenario then plants one defect, or none, and checks the
validator's verdict and counts. A clean copy with the right rules must pass with zero
differences; the same copy without rules shows how many false alarms the rules remove.
"""

from __future__ import annotations

import datetime as dt
import random
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from sfmigrate.resources import resource
from sfmigrate.translator import translate_statement
from sfmigrate.validate.adapters import connect
from sfmigrate.validate.compare import TableSpec, compare_table
from sfmigrate.validate.normalize import Rules

# ---------------------------------------------------------------------------------- translation


@dataclass
class CorpusResult:
    total: int
    passed: int
    failures: list[str]
    status: dict[str, int]
    rules_hit: int

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def run_corpus(path: Path | None = None) -> CorpusResult:
    cases = yaml.safe_load((path or resource("corpus") / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    failures, status, rules = [], {"auto": 0, "assisted": 0, "manual": 0, "dropped": 0}, 0
    for case in cases:
        t = translate_statement(case["source"], case["dialect"])
        status[t.status] += 1
        rules += bool(t.rules)
        problems = []
        if t.output != case["expected"]:
            problems.append(f"output {t.output!r}")
        if t.status != case["status"]:
            problems.append(f"status {t.status}, expected {case['status']}")
        if t.rules != case["rules"]:
            problems.append(f"rules {t.rules}, expected {case['rules']}")
        if problems:
            failures.append(f"{case['id']}: " + "; ".join(problems))
    return CorpusResult(len(cases), len(cases) - len(failures), failures, status, rules)


# ----------------------------------------------------------------------------------- validation

ROWS = 20_000
KOLKATA = dt.timedelta(hours=5, minutes=30)
Row = list[Any]
COLUMNS = ["order_id", "customer_code", "status", "amount", "ordered_at", "note", "region"]


def _source_rows(n: int) -> list[Row]:
    rnd = random.Random(20261107)  # noqa: S311 - deterministic test data
    rows = []
    for i in range(1, n + 1):
        rows.append(
            [
                i,
                f"C{i % 700:04d}".ljust(10),  # CHAR(10): padded in the source
                rnd.choice(["open", "shipped", "paid", "returned"]),
                Decimal(rnd.randint(100, 9_999_999)) / Decimal(10_000),  # NUMERIC(12,4)
                dt.datetime(2024, 1, 1, 9, 0) + dt.timedelta(minutes=i * 13, seconds=i % 60),  # local time, naive
                None if i % 6 == 0 else f"note {i}",  # Oracle-style: '' was stored as NULL
                rnd.choice(["north", "south", "east", "west"]),
            ]
        )
    return rows


def _faithful(row: Row) -> Row:
    """What a correct load into the target produces from one source row."""
    return [row[0], row[1].rstrip(), row[2], row[3], row[4] - KOLKATA, row[5] if row[5] is not None else "", row[6]]


TARGET_DDL = {
    "order_id": "INTEGER",
    "customer_code": "VARCHAR(10)",
    "status": "VARCHAR(20)",
    "amount": "DECIMAL(12,4)",
    "ordered_at": "TIMESTAMP",
    "note": "VARCHAR(100)",
    "region": "VARCHAR(10)",
}
MIGRATION_RULES: dict[str, Any] = {
    "rules": {"trim_trailing": True, "empty_as_null": True},
    "source_rules": {"timestamp_timezone": "Asia/Kolkata"},
}


@dataclass
class Scenario:
    name: str
    title: str
    mutate: Callable[[list[Row], dict[str, str]], None] = lambda rows, ddl: None
    rules: dict[str, Any] = field(default_factory=lambda: dict(MIGRATION_RULES))
    expect_ok: bool = False
    expect: dict[str, int] = field(default_factory=dict)
    expect_checks: list[str] = field(default_factory=list)
    defect: bool = True


def _set(index: int, fn: Callable[[Any], Any], every: int = 1, limit: int | None = None) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        hit = 0
        for r in rows:
            if r[0] % every == 0 and (limit is None or hit < limit):
                r[index] = fn(r[index])
                hit += 1

    return mutate


def _ddl(column: str, sql_type: str, then: Callable[[list[Row], dict[str, str]], None] | None = None) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        ddl[column] = sql_type
        if then:
            then(rows, ddl)

    return mutate


def _drop_column(column: str) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        index = list(ddl).index(column)
        del ddl[column]
        for r in rows:
            del r[index]

    return mutate


def _delete(ids: set[int]) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        rows[:] = [r for r in rows if r[0] not in ids]

    return mutate


def _duplicate(ids: set[int]) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        rows.extend([list(r) for r in rows if r[0] in ids])

    return mutate


def _append(n: int) -> Callable[[list[Row], dict[str, str]], None]:
    def mutate(rows: list[Row], ddl: dict[str, str]) -> None:
        last = max(r[0] for r in rows)
        rows.extend([[last + i, "C9999", "open", Decimal("1.0000"), dt.datetime(2026, 1, 1), "", "north"] for i in range(1, n + 1)])

    return mutate


SCENARIOS = [
    Scenario(
        "clean-copy",
        "Faithful copy, with the migration's normalization rules",
        expect_ok=True,
        expect={"missing": 0, "extra": 0, "changed": 0},
        defect=False,
    ),
    Scenario(
        "clean-copy-no-rules",
        "The same faithful copy compared without rules (false alarms)",
        rules={},
        expect={"missing": 0, "extra": 0},
        defect=False,
    ),
    Scenario(
        "missing-rows",
        "Seven rows never loaded",
        _delete({11, 222, 3333, 4444, 5555, 6666, 17777}),
        expect={"missing": 7, "extra": 0, "changed": 0},
        expect_checks=["row count"],
    ),
    Scenario(
        "duplicate-load",
        "A batch of three rows loaded twice",
        _duplicate({101, 102, 103}),
        expect={"duplicate_keys": 3},
        expect_checks=["row count"],
    ),
    Scenario("extra-rows", "Four rows that do not exist in the source", _append(4), expect={"extra": 4}),
    Scenario(
        "changed-amount",
        "One amount off by 0.50",
        _set(3, lambda v: v + Decimal("0.5"), every=9999, limit=1),
        expect={"changed": 1},
    ),
    Scenario(
        "scale-loss",
        "Amounts stored as DECIMAL(12,2): two digits lost",
        _ddl("amount", "DECIMAL(12,2)", _set(3, lambda v: v.quantize(Decimal("0.01")))),
        expect_checks=["type amount"],
    ),
    Scenario(
        "float-noise",
        "Amounts stored as DOUBLE, within a 0.000001 tolerance",
        _ddl("amount", "DOUBLE", _set(3, float)),
        rules={**MIGRATION_RULES, "rules": {**MIGRATION_RULES["rules"], "numeric_tolerance": 0.000001}},
        expect_ok=True,
        expect={"changed": 0},
        defect=False,
    ),
    Scenario(
        "timezone-not-converted",
        "Timestamps loaded as local time instead of UTC",
        _set(4, lambda v: v + KOLKATA),
        expect={"changed": ROWS},
    ),
    Scenario(
        "time-truncated",
        "The timestamp column created as DATE: the time of day is lost",
        _ddl("ordered_at", "DATE", _set(4, lambda v: v.date())),
        expect_checks=["type ordered_at"],
    ),
    Scenario(
        "nulls-introduced",
        "Five statuses lost on load",
        _set(2, lambda v: None, every=2000, limit=5),
        expect={"changed": 5},
    ),
    Scenario(
        "strings-truncated",
        "Statuses cut to four characters (DuckDB keeps no VARCHAR length)",
        _ddl("status", "VARCHAR(4)", _set(2, lambda v: v[:4])),
        expect_checks=["rows"],
    ),
    Scenario("column-missing", "region never created in the target", _drop_column("region"), expect_checks=["column region"]),
    Scenario(
        "case-changed",
        "Statuses upper-cased by a transformation",
        _set(2, lambda v: v.upper()),
        expect={"changed": ROWS},
    ),
]


@dataclass
class ScenarioResult:
    name: str
    title: str
    ok: bool
    passed: bool
    counts: dict[str, int]
    failed_checks: list[str]
    problems: list[str]
    seconds: float
    defect: bool


def _load_source(source_url: str, rows: list[Row]) -> str:
    """Create legacy.orders in the PostgreSQL source; returns the table name."""
    import psycopg

    with psycopg.connect(source_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS legacy CASCADE")
        conn.execute("CREATE SCHEMA legacy")
        conn.execute(
            "CREATE TABLE legacy.orders (order_id INTEGER PRIMARY KEY, customer_code CHAR(10) NOT NULL, "
            "status VARCHAR(20), amount NUMERIC(12,4), ordered_at TIMESTAMP, note VARCHAR(100), "
            "region VARCHAR(10))"
        )
        with conn.cursor().copy("COPY legacy.orders FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)
    return "legacy.orders"


def _csv(v: Any) -> Any:
    if v is None:
        return "\\N"
    if isinstance(v, dt.datetime):
        return v.isoformat(" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _load_target(path: Path, rows: list[Row], ddl: dict[str, str]) -> None:
    """Bulk-load through CSV, keeping '' and NULL distinct (NULL is written as \\N)."""
    import csv

    import duckdb

    data = path.with_suffix(".csv")
    with data.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        for r in rows:
            writer.writerow([_csv(v) for v in r])
    conn = duckdb.connect(str(path))
    conn.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    conn.execute("DROP TABLE IF EXISTS analytics.orders")
    conn.execute("CREATE TABLE analytics.orders (" + ", ".join(f"{c} {t}" for c, t in ddl.items()) + ")")
    conn.execute(f"COPY analytics.orders FROM '{data}' (FORMAT csv, HEADER false, NULL '\\N', QUOTE '\"')")
    conn.close()
    data.unlink()


def run_validation(source_url: str, rows: int = ROWS, only: list[str] | None = None) -> list[ScenarioResult]:
    base = _source_rows(rows)
    table = _load_source(source_url, base)
    results = []
    workdir = Path(tempfile.mkdtemp())
    for scenario in SCENARIOS:
        if only and scenario.name not in only:
            continue
        target_rows = [_faithful(r) for r in base]
        ddl = dict(TARGET_DDL)
        scenario.mutate(target_rows, ddl)
        db = workdir / f"{scenario.name}.duckdb"
        _load_target(db, target_rows, ddl)
        spec = TableSpec(name="orders", source=table, target="analytics.orders", key=["order_id"], **scenario.rules)
        source, target = connect(source_url), connect(f"duckdb:///{db}")
        started = time.monotonic()
        try:
            report = compare_table(source, target, spec, Rules(), sample=5)
        finally:
            source.close()
            target.close()
        seconds = time.monotonic() - started
        failed = [c.name for c in report.checks if not c.ok]
        problems = []
        if scenario.expect_ok != report.ok:
            problems.append(f"verdict {'pass' if report.ok else 'fail'}, expected {'pass' if scenario.expect_ok else 'fail'}")
        for k, v in scenario.expect.items():
            if report.counts.get(k) != v:
                problems.append(f"{k} {report.counts.get(k)}, expected {v}")
        for check in scenario.expect_checks:
            if check not in failed:
                problems.append(f"check {check!r} did not fail")
        results.append(
            ScenarioResult(
                scenario.name,
                scenario.title,
                report.ok,
                not problems,
                {k: v for k, v in report.counts.items()},
                failed,
                problems,
                seconds,
                scenario.defect,
            )
        )
    return results


def markdown(corpus: CorpusResult, validation: list[ScenarioResult]) -> str:
    total = sum(corpus.status.values())
    lines = [
        "## Translation corpus",
        "",
        f"**{corpus.passed} / {corpus.total}** cases produce their reviewed output. "
        f"{corpus.status['auto']} automatic, {corpus.status['assisted']} assisted, {corpus.status['manual']} manual, "
        f"{corpus.status['dropped']} dropped; rules changed or flagged {corpus.rules_hit} of {total}.",
        "",
    ]
    lines += [f"- {f}" for f in corpus.failures]
    if validation:
        lines += [
            "",
            "## Validation against injected defects",
            "",
            "| Scenario | Verdict | Missing | Extra | Changed | Duplicate keys | Failed checks | Seconds | Expected |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in validation:
            c = r.counts
            lines.append(
                f"| {r.title} | {'pass' if r.ok else 'fail'} | {c.get('missing', 0)} | {c.get('extra', 0)} | "
                f"{c.get('changed', 0)} | {c.get('duplicate_keys', 0)} | {', '.join(r.failed_checks) or '-'} | "
                f"{r.seconds:.2f} | {'yes' if r.passed else '**no**'} |"
            )
        defects = [r for r in validation if r.defect]
        clean = [r for r in validation if r.name == "clean-copy"]
        lines += [
            "",
            f"Defects detected: **{sum(not r.ok for r in defects)} / {len(defects)}**. "
            f"False alarms on the clean copy with rules: **{clean[0].counts.get('changed', 0) if clean else '-'}**.",
        ]
        for r in validation:
            lines += [f"- {r.name}: {p}" for p in r.problems]
    return "\n".join(lines) + "\n"
