from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from sfmigrate.cli import main
from sfmigrate.evaluation import SCENARIOS, markdown, run_corpus, run_validation
from sfmigrate.validate import normalize
from sfmigrate.validate.adapters import AdapterError, Column, connect
from sfmigrate.validate.compare import Config, TableSpec, compare_table, family
from sfmigrate.validate.normalize import Rules


def test_normalization_rules() -> None:
    plain = Rules()
    assert normalize.value("ab  ", plain) == "ab  "
    rules = Rules(trim_trailing=True, empty_as_null=True, case_insensitive=True, timestamp_precision=3, date_equals_midnight=True)
    assert normalize.value("AB  ", rules) == "ab"
    assert normalize.value("   ", rules) is None
    assert normalize.value(1.5, plain) == Decimal("1.5") and normalize.value(True, plain) is True
    local = dt.datetime(2024, 1, 1, 10, 0, 0, 123456)
    assert normalize.value(local, rules, "Asia/Kolkata") == dt.datetime(2024, 1, 1, 4, 30, 0, 123000)
    aware = dt.datetime(2024, 1, 1, 10, tzinfo=dt.UTC)
    assert normalize.value(aware, plain) == dt.datetime(2024, 1, 1, 10)
    assert normalize.value(dt.date(2024, 1, 2), rules) == dt.datetime(2024, 1, 2)
    assert normalize.value(dt.date(2024, 1, 2), plain) == dt.date(2024, 1, 2)
    assert normalize.value(b"\x01\x02", plain) == "0102"
    assert normalize.value(object, plain) is object
    assert normalize.equal(Decimal("1.00001"), Decimal("1"), Rules(numeric_tolerance=0.0001))
    assert not normalize.equal(None, Decimal(1), plain) and normalize.equal(None, None, plain)
    assert normalize.key((None, "a", 3)) < normalize.key(("a", "a", 3))
    assert plain.merged({"trim_trailing": True}).trim_trailing


def test_type_families() -> None:
    assert family(Column("a", "numeric", True, 10, 0)) == "integer"
    assert family(Column("a", "number(10)", True)) == "integer"
    assert family(Column("a", "timestamp with time zone", True)) == "timestamp"
    assert family(Column("a", "bytea", True)) == "binary"
    assert family(Column("a", "geometry", True)) == "geometry"


def _sqlite(path: Path, rows: list[tuple[object, ...]]) -> str:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER, code VARCHAR(5), amount NUMERIC(10,2))")
    conn.executemany("INSERT INTO t VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def test_sqlite_to_duckdb(tmp_path: Path) -> None:
    src = _sqlite(tmp_path / "s.db", [(1, "a", 1.5), (2, "b", 2.0), (3, "c", 3.25), (3, "c", 3.25)])
    target = tmp_path / "t.duckdb"
    conn = duckdb.connect(str(target))
    conn.execute("CREATE TABLE t (id INTEGER, code VARCHAR, amount DECIMAL(10,2), extra INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?,?,?,?)", [(1, "a", 1.5, 0), (2, "B", 2.0, 0), (4, "d", 4, 0)])
    conn.close()
    config = Config(source=src, target=f"duckdb:///{target}", tables=[TableSpec(name="t", source="t", target="t", key=["id"])])
    s, t = connect(config.source), connect(config.target)
    report = compare_table(s, t, config.tables[0], config.rules, sample=5)
    s.close()
    t.close()
    c = report.counts
    assert (c["missing"], c["extra"], c["changed"], c["duplicate_keys"]) == (1, 1, 1, 1)
    assert not report.ok and report.changed[0]["columns"]["code"] == {"source": "b", "target": "B"}
    assert any(ch.name == "column extra" and ch.severity == "warning" for ch in report.checks)
    md = __import__("sfmigrate.validate.compare", fromlist=["Report"]).Report([report]).markdown()
    assert "FAIL" in md and "missing in target" in md and "only in target" in md


def test_config_and_cli(tmp_path: Path) -> None:
    src = _sqlite(tmp_path / "s.db", [(1, "a", 1.5)])
    tgt = _sqlite(tmp_path / "t.db", [(1, "a", 1.5)])
    cfg = tmp_path / "v.yaml"
    cfg.write_text(f"source: {src}\ntarget: {tgt}\ntables:\n  - {{name: t, source: t, target: t, key: [id]}}\n")
    assert main(["validate", str(cfg), "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")]) == 0
    assert "PASS" in (tmp_path / "r.md").read_text()
    bad = tmp_path / "bad.yaml"
    bad.write_text(f"source: {src}\ntarget: {tgt}\ntables:\n  - {{name: t, source: t, target: nope, key: [id]}}\n")
    assert main(["validate", str(bad)]) == 1
    missing_key = tmp_path / "k.yaml"
    missing_key.write_text(f"source: {src}\ntarget: {tgt}\ntables:\n  - {{name: t, source: t, target: t, key: [zz]}}\n")
    assert main(["validate", str(missing_key)]) == 1


def test_adapter_guards() -> None:
    with pytest.raises(AdapterError, match="unsupported"):
        connect("mysql://x")
    a = connect("sqlite:///:memory:")
    with pytest.raises(AdapterError, match="unsafe identifier"):
        a.count("t; DROP TABLE x", None)
    a.close()


def test_validation_scenarios_on_postgres(pg: str) -> None:
    results = run_validation(pg)
    assert [r.name for r in results] == [s.name for s in SCENARIOS]
    assert not [(r.name, r.problems) for r in results if not r.passed]
    text = markdown(run_corpus(), results)
    assert "Defects detected" in text and "False alarms on the clean copy with rules: **0**" in text


def test_merge_falls_back_when_orders_disagree(pg: str, tmp_path: Path) -> None:
    import psycopg

    with psycopg.connect(pg, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS public.keys_text")
        conn.execute("CREATE TABLE public.keys_text (k TEXT, v INTEGER)")
        conn.execute("INSERT INTO public.keys_text VALUES ('a', 1), ('B', 2), ('_', 3)")
    target = tmp_path / "t.duckdb"
    d = duckdb.connect(str(target))
    d.execute("CREATE TABLE keys_text (k VARCHAR, v INTEGER)")
    d.execute("INSERT INTO keys_text VALUES ('a', 1), ('B', 2), ('_', 3)")
    d.close()
    s, t = connect(pg), connect(f"duckdb:///{target}")
    report = compare_table(s, t, TableSpec(name="k", source="public.keys_text", target="keys_text", key=["k"]), Rules())
    s.close()
    t.close()
    assert report.ok and report.counts["compared"] == 3
