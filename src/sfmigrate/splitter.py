"""Split legacy scripts into statements.

Handles quoted strings and identifiers, line and block comments, Teradata BTEQ dot-commands
(``.LOGON``, ``.IF ERRORCODE``, ...), and Oracle PL/SQL blocks, which run to a line holding only
``/`` rather than to the first semicolon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TD_PROCEDURE = re.compile(r"^\s*(CREATE|REPLACE)\s+PROCEDURE\b", re.IGNORECASE)
BLOCK_OPEN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
BLOCK_CLOSE = re.compile(r"\bEND\b(?!\s+(IF|LOOP|WHILE|CASE|FOR|REPEAT)\b)", re.IGNORECASE)
PLSQL_START = re.compile(
    r"^\s*(DECLARE\b|BEGIN\b|CREATE\s+(OR\s+REPLACE\s+)?(PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE\s+BODY)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Piece:
    text: str
    line: int
    kind: str  # "sql", "bteq" or "plsql"


def split(script: str, dialect: str) -> list[Piece]:
    pieces: list[Piece] = []
    lines = script.splitlines()
    buffer: list[str] = []
    start = 0
    i = 0
    in_plsql = False
    in_procedure = False
    depth = 0

    def flush(kind: str = "sql") -> None:
        nonlocal buffer
        raw = "\n".join(buffer)
        text = raw.strip()
        if text:
            first = start + 1 + raw[: len(raw) - len(raw.lstrip())].count("\n")
            pieces.extend(_split_sql(text, first) if kind == "sql" else [Piece(text, first, kind)])
        buffer = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_procedure:
            buffer.append(line)
            depth += len(BLOCK_OPEN.findall(line)) - len(BLOCK_CLOSE.findall(line))
            i += 1
            if depth <= 0 and BLOCK_CLOSE.search(line):
                text = "\n".join(buffer).strip().rstrip(";")
                pieces.append(Piece(text, start + 1, "sql"))
                buffer = []
                in_procedure = False
            continue
        if in_plsql:
            if stripped == "/":
                flush("plsql")
                in_plsql = False
            else:
                buffer.append(line)
            i += 1
            continue
        if dialect == "teradata" and stripped.startswith(".") and not buffer_has_open_quote(buffer):
            flush()
            pieces.append(Piece(stripped, i + 1, "bteq"))
            i += 1
            start = i
            continue
        if dialect == "teradata" and _at_boundary(buffer) and TD_PROCEDURE.match(line):
            flush()
            start = i
            in_procedure = True
            buffer.append(line)
            depth = len(BLOCK_OPEN.findall(line)) - len(BLOCK_CLOSE.findall(line))
            i += 1
            if depth <= 0 and BLOCK_CLOSE.search(line):
                pieces.append(Piece("\n".join(buffer).strip().rstrip(";"), start + 1, "sql"))
                buffer = []
                in_procedure = False
            continue
        if dialect == "oracle" and _at_boundary(buffer) and PLSQL_START.match(line):
            flush()
            start = i
            in_plsql = True
            buffer.append(line)
            i += 1
            continue
        if not buffer:
            start = i
        buffer.append(line)
        i += 1
    flush("plsql" if in_plsql else "sql")
    return pieces


def _at_boundary(buffer: list[str]) -> bool:
    """True when everything buffered so far is complete statements (ends in ';') or nothing."""
    text = re.sub(r"--[^\n]*|/\*.*?\*/", "", "\n".join(buffer), flags=re.S).strip()
    return not text or (text.endswith(";") and not buffer_has_open_quote(buffer))


def buffer_has_open_quote(buffer: list[str]) -> bool:
    return "\n".join(buffer).count("'") % 2 == 1


def _split_sql(text: str, first_line: int) -> list[Piece]:
    """Split on semicolons outside quotes and comments."""
    out: list[Piece] = []
    current: list[str] = []
    line = first_line
    stmt_line = first_line
    i = 0
    quote: str | None = None
    parens = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            current.append(ch)
            if ch == quote:
                if nxt == quote:  # escaped quote
                    current.append(nxt)
                    i += 1
                else:
                    quote = None
        elif ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch == "-" and nxt == "-":
            end = text.find("\n", i)
            end = len(text) if end == -1 else end
            current.append(text[i:end])
            i = end - 1
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end + 2
            current.append(text[i:end])
            line += text[i:end].count("\n")
            i = end - 1
        elif ch == "(":
            parens += 1
            current.append(ch)
        elif ch == ")":
            parens = max(0, parens - 1)
            current.append(ch)
        elif ch == ";" and parens == 0:
            stmt = "".join(current).strip()
            if _has_code(stmt):
                out.append(Piece(stmt, stmt_line, "sql"))
            current = []
            stmt_line = line
        else:
            if ch == "\n":
                line += 1
                if not "".join(current).strip():
                    stmt_line = line
            current.append(ch)
        i += 1
    stmt = "".join(current).strip()
    if _has_code(stmt):
        out.append(Piece(stmt, stmt_line, "sql"))
    return out


def _has_code(stmt: str) -> bool:
    without = re.sub(r"--[^\n]*|/\*.*?\*/", "", stmt, flags=re.S)
    return bool(without.strip())
