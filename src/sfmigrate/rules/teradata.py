"""Teradata (including BTEQ scripts) to Snowflake."""

from __future__ import annotations

import re

from sqlglot import exp

from sfmigrate.model import Translation
from sfmigrate.rules import describe

describe(
    "TD001",
    "teradata",
    "BTEQ commands",
    "Dot-commands (.LOGON, .IF ERRORCODE, .QUIT) are dropped; orchestration moves to the scheduler",
)
describe(
    "TD002",
    "teradata",
    "SET / MULTISET tables",
    "Dropped; a SET table silently discarded duplicate rows, Snowflake keeps them",
)
describe("TD003", "teradata", "Physical table options", "FALLBACK, JOURNAL, CHECKSUM, FREESPACE and similar are dropped")
describe(
    "TD004",
    "teradata",
    "Primary and secondary indexes",
    "Dropped; a UNIQUE index's guarantee is lost, consider CLUSTER BY for large tables",
)
describe(
    "TD005",
    "teradata",
    "Column attributes",
    "CHARACTER SET, FORMAT, TITLE, COMPRESS dropped; NOT CASESPECIFIC becomes COLLATE 'en-ci'",
)
describe(
    "TD006",
    "teradata",
    "Volatile tables",
    "VOLATILE becomes TEMPORARY; WITH DATA and ON COMMIT are dropped; WITH NO DATA adds LIMIT 0",
)
describe("TD007", "teradata", "COLLECT STATISTICS", "Statement dropped; Snowflake maintains statistics itself")
describe("TD008", "teradata", "INDEX(string, substring)", "Becomes CHARINDEX(substring, string)")
describe(
    "TD009",
    "teradata",
    "UPDATE ... FROM",
    "Teradata's UPDATE t FROM a, b SET ... is rewritten to UPDATE t SET ... FROM ...",
)
describe("TD010", "teradata", "TITLE phrase in queries", "(TITLE '...') is dropped; use a column alias")
describe("TD011", "teradata", "CAST ... FORMAT", "Translated, but FORMAT in Teradata is also display formatting: review")
describe(
    "TD012",
    "teradata",
    "Macros, procedures, temporal SQL",
    "Not translated: MACRO, PROCEDURE, NORMALIZE, EXPAND ON, PERIOD need a person",
)
describe("TD013", "teradata", "DATABASE statement", "Becomes USE SCHEMA")

MANUAL = re.compile(
    r"\b(CREATE|REPLACE)\s+(MACRO|PROCEDURE)\b|\bEXEC(UTE)?\s+\w+|\bNORMALIZE\b|\bEXPAND\s+ON\b|\bPERIOD\s*\(",
    re.IGNORECASE,
)
CAST_FORMAT = re.compile(r"\bCAST\s*\((?:[^()]|\([^()]*\))*\bFORMAT\s+'", re.IGNORECASE)
TITLE = re.compile(r"\(\s*TITLE\s+'(?:[^']|'')*'\s*\)", re.IGNORECASE)
UPDATE_FROM = re.compile(
    r"^\s*UPD(?:ATE)?\s+(?P<target>[\w.\"]+)\s+FROM\s+(?P<sources>.+?)\s+SET\s+(?P<sets>.+?)(?P<where>\s+WHERE\s+.+)?$",
    re.IGNORECASE | re.DOTALL,
)
PHYSICAL = (
    exp.FallbackProperty,
    exp.JournalProperty,
    exp.ChecksumProperty,
    exp.FreespaceProperty,
    exp.MergeBlockRatioProperty,
    exp.DataBlocksizeProperty,
    exp.BlockCompressionProperty,
    exp.IsolatedLoadingProperty,
)


def _split_top(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def text_rules(sql: str, t: Translation) -> str:
    if MANUAL.search(sql):
        t.note("TD012", "manual", "macros, stored procedures and temporal SQL need to be rewritten by hand")
        return sql
    if CAST_FORMAT.search(sql):
        t.note(
            "TD011",
            "warning",
            "CAST ... FORMAT translated as a conversion; check it was not used only to format output",
        )
    if TITLE.search(sql):
        sql = TITLE.sub("", sql)
        t.note("TD010", "info", "TITLE display attributes were dropped; use column aliases if they matter")
    match = UPDATE_FROM.match(sql)
    if match:
        target = match.group("target")
        sources = _split_top(match.group("sources"))
        chosen, others = None, []
        for source in sources:
            words = source.replace(" AS ", " ").replace(" as ", " ").split()
            name, alias = words[0], words[-1]
            if chosen is None and (alias.lower() == target.lower() or name.lower() == target.lower()):
                chosen = source
            else:
                others.append(source)
        if chosen is None:
            t.note("TD009", "manual", f"UPDATE {target} FROM ...: the target is not one of the FROM tables")
            return sql
        sql = f"UPDATE {chosen} SET {match.group('sets')}"  # noqa: S608 - SQL text being translated, not run
        if others:
            sql += " FROM " + ", ".join(others)
        sql += match.group("where") or ""
        t.note("TD009", "info", "Teradata UPDATE ... FROM rewritten to Snowflake's UPDATE ... SET ... FROM")
    return sql


def tree_rules(tree: exp.Expression, t: Translation) -> exp.Expression:
    if isinstance(tree, exp.Command) and tree.name.upper() == "COLLECT":
        t.dropped = True
        t.note("TD007", "info", "COLLECT STATISTICS dropped: Snowflake maintains statistics automatically")
        return tree
    if isinstance(tree, exp.Use):
        t.note("TD013", "info", "DATABASE became USE SCHEMA: a Teradata database maps to a Snowflake schema")
        tree.set("kind", exp.Var(this="SCHEMA"))
    if isinstance(tree, exp.Create):
        _create(tree, t)
    for node in list(tree.find_all(exp.Anonymous)):
        if node.name.upper() == "INDEX" and len(node.expressions) == 2:
            node.replace(exp.StrPosition(this=node.expressions[0], substr=node.expressions[1]))
            t.note("TD008", "info", "INDEX(string, substring) became CHARINDEX(substring, string)")
    return tree


def _create(tree: exp.Create, t: Translation) -> None:
    properties = tree.args.get("properties")
    if properties is not None:
        kept: list[exp.Expression] = []
        no_data = False
        for prop in properties.expressions:
            if isinstance(prop, exp.SetProperty):
                if prop.args.get("multi"):
                    t.note("TD002", "info", "MULTISET dropped: Snowflake tables allow duplicate rows like MULTISET")
                else:
                    t.note("TD002", "warning", "SET table: Teradata silently discarded duplicate rows; deduplicate on load")
            elif isinstance(prop, PHYSICAL):
                t.note("TD003", "info", f"physical option {prop.key} dropped")
            elif isinstance(prop, exp.VolatileProperty):
                kept.append(exp.TemporaryProperty())
                t.note("TD006", "info", "VOLATILE table became TEMPORARY (session-scoped in both)")
            elif isinstance(prop, exp.WithDataProperty):
                no_data = bool(prop.args.get("no"))
            elif isinstance(prop, exp.OnCommitProperty):
                t.note(
                    "TD006",
                    "info",
                    "ON COMMIT PRESERVE ROWS dropped: Snowflake temporary tables keep rows for the session",
                )
            else:
                kept.append(prop)
        properties.set("expressions", kept)
        if not kept:
            tree.set("properties", None)
        query = tree.expression
        if no_data and isinstance(query, (exp.Query, exp.Subquery)):
            inner = query.unnest() if isinstance(query, exp.Subquery) else query
            if isinstance(inner, exp.Select):
                inner.limit(0, copy=False)
                t.note("TD006", "info", "WITH NO DATA became LIMIT 0: the table is created empty")
    indexes = tree.args.get("indexes") or []
    if indexes:
        unique = any(i.args.get("unique") for i in indexes)
        if unique:
            t.note("TD004", "warning", "UNIQUE index dropped: Snowflake does not enforce uniqueness; check it on load")
        else:
            t.note(
                "TD004",
                "info",
                "PRIMARY INDEX dropped: distribution is automatic; consider CLUSTER BY for large tables",
            )
        tree.set("indexes", None)
    for coldef in tree.find_all(exp.ColumnDef):
        constraints = []
        for c in coldef.args.get("constraints") or []:
            kind = c.args.get("kind")
            if isinstance(kind, exp.CaseSpecificColumnConstraint):
                if kind.args.get("not_"):
                    constraints.append(exp.ColumnConstraint(kind=exp.CollateColumnConstraint(this=exp.Literal.string("en-ci"))))
                    t.note(
                        "TD005",
                        "warning",
                        f"{coldef.name}: NOT CASESPECIFIC became COLLATE 'en-ci'; comparisons stay case-insensitive",
                    )
                continue
            if isinstance(
                kind,
                (
                    exp.CharacterSetColumnConstraint,
                    exp.DateFormatColumnConstraint,
                    exp.TitleColumnConstraint,
                    exp.CompressColumnConstraint,
                    exp.InlineLengthColumnConstraint,
                ),
            ):
                t.note("TD005", "info", f"{coldef.name}: {kind.key.replace('columnconstraint', '')} attribute dropped")
                continue
            constraints.append(c)
        coldef.set("constraints", constraints)
