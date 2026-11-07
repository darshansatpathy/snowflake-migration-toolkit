"""Oracle to Snowflake."""

from __future__ import annotations

import re
from typing import cast

from sqlglot import exp
from sqlglot.transforms import eliminate_join_marks

from sfmigrate.model import Translation
from sfmigrate.rules import describe

describe(
    "OR001",
    "oracle",
    "ROWNUM",
    "WHERE ROWNUM <= n becomes LIMIT n; with ORDER BY, a subquery keeps Oracle's limit-then-sort meaning",
)
describe("OR002", "oracle", "(+) outer joins", "Rewritten to ANSI LEFT JOIN")
describe(
    "OR003",
    "oracle",
    "SYSDATE and SYSTIMESTAMP",
    "SYSTIMESTAMP becomes CURRENT_TIMESTAMP; SYSDATE is flagged: Snowflake returns UTC",
)
describe("OR004", "oracle", "DATE type", "Oracle DATE holds a time of day: it becomes TIMESTAMP_NTZ(0), not DATE")
describe("OR005", "oracle", "TO_DATE with a time format", "Becomes TO_TIMESTAMP, so the time is not dropped")
describe(
    "OR006",
    "oracle",
    "NUMBER without precision",
    "Becomes NUMBER(38, 10) instead of Snowflake's NUMBER(38, 0), which would drop decimals",
)
describe("OR007", "oracle", "Empty strings", "Flagged: Oracle treats '' as NULL, Snowflake does not")
describe(
    "OR008",
    "oracle",
    "PL/SQL",
    "Not translated: blocks, procedures, functions, packages and triggers need Snowflake Scripting",
)
describe("OR009", "oracle", "CONNECT BY", "Kept (Snowflake supports it); flagged for review")
describe(
    "OR011",
    "oracle",
    "Date arithmetic",
    "date +/- n adds days in Oracle; Snowflake timestamps need DATEADD(DAY, n, ...)",
)
describe("OR010", "oracle", "LOB types", "CLOB and NCLOB become VARCHAR, BLOB becomes BINARY; check the size limits")

LOB = re.compile(r"\b(N?CLOB|BLOB|LONG\s+RAW|LONG)\b", re.IGNORECASE)
TIME_FORMAT = re.compile(r"%[HIMSfp]")
DATE_LIKE_NAME = re.compile(r"(date|_dt$|_at$|time|created|updated|modified|day)", re.IGNORECASE)
DATE_EXPRESSIONS = (exp.CurrentTimestamp, exp.CurrentDate, exp.StrToDate, exp.StrToTime, exp.TsOrDsToDate)


def text_rules(sql: str, t: Translation) -> str:
    if LOB.search(sql) and re.search(r"\bCREATE\b|\bALTER\b|\bCAST\b", sql, re.IGNORECASE):
        t.note("OR010", "info", "LOB column mapped to VARCHAR/BINARY: check values fit Snowflake's size limits")
    return sql


def tree_rules(tree: exp.Expression, t: Translation) -> exp.Expression:
    if any(c.args.get("join_mark") for c in tree.find_all(exp.Column)):
        tree = cast(exp.Expression, eliminate_join_marks(tree))
        t.note("OR002", "info", "(+) outer join rewritten to ANSI LEFT JOIN")
    for select in list(tree.find_all(exp.Select)):
        replaced = _rownum(select, t)
        if replaced is not None and select is tree:
            tree = replaced
    for systimestamp in list(tree.find_all(exp.Systimestamp)):
        systimestamp.replace(exp.CurrentTimestamp())
        t.note("OR003", "info", "SYSTIMESTAMP became CURRENT_TIMESTAMP()")
    for current in tree.find_all(exp.CurrentTimestamp):
        if current.args.get("sysdate"):
            t.note(
                "OR003",
                "warning",
                "SYSDATE is the database host's local time in Oracle, UTC in Snowflake: check the session time zone",
            )
    for to_date in list(tree.find_all(exp.StrToDate)):
        fmt = to_date.args.get("format")
        if isinstance(fmt, exp.Literal) and TIME_FORMAT.search(fmt.this):
            to_date.replace(exp.StrToTime(this=to_date.this, format=fmt))
            t.note("OR005", "info", "TO_DATE with a time format became TO_TIMESTAMP so the time is kept")
    for dtype in list(tree.find_all(exp.DataType)):
        if dtype.this == exp.DataType.Type.DATE:
            dtype.replace(exp.DataType.build("TIMESTAMP_NTZ(0)", dialect="snowflake"))
            t.note("OR004", "info", "Oracle DATE became TIMESTAMP_NTZ(0): Oracle DATE values carry a time of day")
        elif dtype.this == exp.DataType.Type.DECIMAL and not dtype.expressions:
            dtype.replace(exp.DataType.build("NUMBER(38, 10)", dialect="snowflake"))
            t.note("OR006", "warning", "NUMBER without precision became NUMBER(38, 10); confirm the scale the data needs")
    for lit in tree.find_all(exp.Literal):
        if lit.is_string and lit.this == "" and not isinstance(lit.parent, (exp.Anonymous, exp.RegexpReplace)):
            t.note(
                "OR007",
                "warning",
                "'' is NULL in Oracle but an empty string in Snowflake: comparisons and NVL behave differently",
            )
            break
    _date_arithmetic(tree, t)
    if tree.find(exp.Connect):
        t.note("OR009", "info", "CONNECT BY kept: Snowflake supports it; a recursive CTE is the portable alternative")
    return tree


def _is_rownum(node: exp.Expression) -> bool:
    return isinstance(node, exp.Column) and node.name.upper() == "ROWNUM" and not node.table


def _rownum(select: exp.Select, t: Translation) -> exp.Expression | None:
    where = select.args.get("where")
    uses = [c for c in select.find_all(exp.Column) if _is_rownum(c) and c.find_ancestor(exp.Select) is select]
    if not uses:
        return None
    if where is None:
        t.note("OR001", "manual", "ROWNUM used outside WHERE: rewrite with ROW_NUMBER()")
        return None
    conjuncts = cast(list[exp.Expression], list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this])
    limit: int | None = None
    rest: list[exp.Expression] = []
    for c in conjuncts:
        n = _limit_of(c)
        if n is None:
            rest.append(c)
        else:
            limit = n if limit is None else min(limit, n)
    if limit is None or any(any(_is_rownum(x) for x in r.find_all(exp.Column)) for r in rest):
        t.note("OR001", "manual", "this use of ROWNUM has no direct LIMIT equivalent: rewrite with ROW_NUMBER()")
        return None
    if rest:
        select.set("where", exp.Where(this=exp.and_(*rest)))
    else:
        select.set("where", None)
    order = select.args.get("order")
    if order is None:
        select.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
        t.note("OR001", "info", f"WHERE ROWNUM <= {limit} became LIMIT {limit}")
        return None
    select.set("order", None)
    inner = select.copy()
    inner.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
    outer_order = order.copy()
    for col in outer_order.find_all(exp.Column):
        col.set("table", None)
    replacement = exp.select("*").from_(inner.subquery("limited")).order_by(*outer_order.expressions)
    select.replace(replacement)
    t.note(
        "OR001",
        "warning",
        "ROWNUM with ORDER BY: Oracle limits before sorting, kept with a subquery; confirm that was intended",
    )
    return replacement


def _limit_of(node: exp.Expression) -> int | None:
    def num(x: exp.Expression) -> int | None:
        return int(x.this) if isinstance(x, exp.Literal) and not x.is_string and str(x.this).isdigit() else None

    if isinstance(node, exp.LTE) and _is_rownum(node.this):
        return num(node.expression)
    if isinstance(node, exp.LT) and _is_rownum(node.this):
        n = num(node.expression)
        return None if n is None else n - 1
    if isinstance(node, exp.EQ) and _is_rownum(node.this) and num(node.expression) == 1:
        return 1
    if isinstance(node, exp.GTE) and _is_rownum(node.expression):
        return num(node.this)
    return None


def _date_arithmetic(tree: exp.Expression, t: Translation) -> None:
    """Oracle adds days with + and -. Snowflake does too for DATE, but Oracle DATE maps to TIMESTAMP_NTZ."""
    for node in list(tree.find_all(exp.Add, exp.Sub)):
        left, right = node.this, node.expression
        if not (isinstance(right, exp.Literal) and not right.is_string):
            continue
        days = right.copy() if isinstance(node, exp.Add) else exp.Neg(this=right.copy())
        if isinstance(left, DATE_EXPRESSIONS):
            node.replace(exp.DateAdd(this=left.copy(), expression=days, unit=exp.var("DAY")))
            t.note("OR011", "info", "date +/- n became DATEADD(DAY, n, ...)")
        elif isinstance(left, exp.Column) and DATE_LIKE_NAME.search(left.name):
            t.note(
                "OR011",
                "warning",
                f"{left.sql()} +/- n: if it is a DATE column (now TIMESTAMP_NTZ), use DATEADD(DAY, n, ...)",
            )
