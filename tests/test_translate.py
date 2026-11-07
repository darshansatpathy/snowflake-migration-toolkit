from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot

from sfmigrate.evaluation import run_corpus
from sfmigrate.splitter import split
from sfmigrate.translator import detect_dialect, translate_statement, translate_text


def test_corpus_is_exact() -> None:
    result = run_corpus()
    assert result.ok, result.failures
    assert result.total >= 50


@pytest.mark.parametrize(
    ("dialect", "sql", "status", "fragment"),
    [
        ("oracle", "SELECT * FROM t WHERE ROWNUM = 1", "auto", "LIMIT 1"),
        ("oracle", "SELECT * FROM t WHERE 20 >= ROWNUM", "auto", "LIMIT 20"),
        ("oracle", "SELECT * FROM t WHERE ROWNUM > 5", "manual", ""),
        ("oracle", "SELECT * FROM t WHERE ROWNUM <= 5 OR x = 1", "manual", ""),
        ("oracle", "SELECT * FROM (SELECT * FROM t WHERE ROWNUM <= 3) s", "auto", "LIMIT 3"),
        ("oracle", "SELECT TO_DATE(d, 'YYYY-MM-DD HH24:MI:SS') + 1 FROM t", "auto", "DATEADD(DAY, 1, TO_TIMESTAMP"),
        ("oracle", "SELECT updated_at - 1 FROM t", "assisted", "updated_at - 1"),
        ("oracle", "SELECT amount - 1 FROM t", "auto", "amount - 1"),
        ("oracle", "SELECT REGEXP_REPLACE(a, 'x', '') FROM t", "auto", "REGEXP_REPLACE"),
        ("teradata", "UPDATE x FROM a, b SET v = 1", "manual", ""),
        ("teradata", "UPDATE a FROM a, b SET v = b.v WHERE a.id = b.id", "auto", "UPDATE a SET v = b.v FROM b"),
        ("teradata", "UPDATE a FROM a SET v = 1", "auto", "UPDATE a SET v = 1"),
        ("teradata", "HELP TABLE t", "manual", ""),
        ("teradata", "SELECT FROM WHERE", "manual", ""),
    ],
)
def test_rules(dialect: str, sql: str, status: str, fragment: str) -> None:
    t = translate_statement(sql, dialect)
    assert t.status == status, (t.output, t.notes)
    assert fragment in t.output
    if t.output:
        sqlglot.parse_one(t.output, read="snowflake")


def test_unknown_dialect_and_empty() -> None:
    with pytest.raises(ValueError):
        translate_statement("SELECT 1", "db2")
    t = translate_statement("-- only a comment", "oracle")
    assert t.status == "dropped"


def test_translation_round_trip() -> None:
    t = translate_statement("SELECT 1 FROM dual", "oracle")
    data = t.to_dict()
    assert data["status"] == "auto" and data["output"] == "SELECT 1 FROM dual"
    t.note("X", "info", "a")
    t.note("X", "info", "a")
    assert len(t.notes) == 1


def test_splitter_handles_quotes_comments_and_blocks() -> None:
    script = """
-- leading comment ; with a semicolon
SELECT 'a;b' AS x;  /* block ; comment */
SELECT "c;d" FROM t;

CREATE OR REPLACE PROCEDURE p AS
BEGIN
  NULL;
END;
/
SELECT 'it''s' FROM dual
"""
    pieces = split(script, "oracle")
    assert [p.kind for p in pieces] == ["sql", "sql", "plsql", "sql"]
    assert pieces[0].text.endswith("AS x") and "'a;b'" in pieces[0].text
    assert pieces[3].line == 11 and "it''s" in pieces[3].text
    td = split(".LOGON x/y\nSEL 1;\n.IF ERRORCODE <> 0 THEN .QUIT 8\nREPLACE MACRO m AS (SEL 1; SEL 2;);\n", "teradata")
    assert [p.kind for p in td] == ["bteq", "sql", "bteq", "sql"]
    assert td[3].text.startswith("REPLACE MACRO")
    proc = split("CREATE PROCEDURE p () BEGIN SELECT 1; END;\nSEL 2;", "teradata")
    assert len(proc) == 2


def test_translate_text_writes_reviewable_scripts() -> None:
    result = translate_text(
        ".LOGON a/b;\nSEL 1;\nREPLACE MACRO m AS (SEL 1;);\nCOLLECT STATISTICS ON t COLUMN (a);\n",
        "teradata",
        "job.bteq",
    )
    script = result.script()
    assert "-- [dropped] line 1" in script and "SELECT\n  1;" in script
    assert "-- REPLACE MACRO" in script and "[manual]" in script


def test_detect_dialect(tmp_path: Path) -> None:
    assert detect_dialect(Path("x/teradata/a.sql")) == "teradata"
    assert detect_dialect(Path("job.bteq")) == "teradata"
    assert detect_dialect(Path("pkg.pkb")) == "oracle"
    assert detect_dialect(Path("a.sql"), "oracle") == "oracle"
    with pytest.raises(ValueError, match="cannot tell"):
        detect_dialect(Path("a.sql"))
