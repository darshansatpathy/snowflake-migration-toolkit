"""Translate Teradata or Oracle SQL to Snowflake: sqlglot's transpiler plus the rules.

Every statement ends in one of four states: ``auto`` (translated, nothing to review),
``assisted`` (translated, with warnings a person should check), ``manual`` (not translated,
with the reason), or ``dropped`` (deliberately removed, such as COLLECT STATISTICS). Output is
only accepted if Snowflake's grammar in sqlglot parses it back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, UnsupportedError

from sfmigrate.model import Translation
from sfmigrate.rules import oracle, teradata
from sfmigrate.splitter import split

logging.getLogger("sqlglot").setLevel(logging.ERROR)  # every problem is reported as a note instead

DIALECTS = ("teradata", "oracle")
RULES = {"teradata": teradata, "oracle": oracle}


def _describe(tree: exp.Expression) -> tuple[str, str]:
    if isinstance(tree, exp.Create):
        kind = str(tree.args.get("kind") or "object").lower()
        target = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        return kind, target.sql() if isinstance(target, exp.Expression) else ""
    for cls, kind in (
        (exp.Insert, "insert"),
        (exp.Update, "update"),
        (exp.Delete, "delete"),
        (exp.Merge, "merge"),
        (exp.Query, "query"),
        (exp.Drop, "drop"),
        (exp.Use, "use"),
    ):
        if isinstance(tree, cls):
            table = tree.find(exp.Table)
            return kind, table.sql() if table is not None else ""
    return tree.key, ""


def translate_statement(sql: str, dialect: str, *, pretty: bool = False) -> Translation:
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}; use one of {DIALECTS}")
    t = Translation(dialect=dialect, source=sql.strip())
    rules = RULES[dialect]
    text = rules.text_rules(sql.strip().rstrip(";"), t)
    if _manual(t):
        return t
    # A statement a text rule has already rewritten into Snowflake syntax is parsed as Snowflake.
    read = "snowflake" if "TD009" in t.rules else dialect
    try:
        trees = sqlglot.parse(text, read=read, error_level=ErrorLevel.RAISE)
    except ParseError as exc:
        t.note("PARSE", "manual", f"could not parse as {dialect}: {_first_line(exc)}")
        return t
    tree = trees[0] if trees else None
    if tree is None:
        t.dropped = True
        return t
    tree = rules.tree_rules(tree, t)
    t.kind, t.name = _describe(tree)
    if t.dropped or _manual(t):
        return t
    if isinstance(tree, exp.Command):
        t.note("UNSUPPORTED", "manual", f"{tree.name} statements have no Snowflake equivalent here")
        return t
    try:
        output = tree.sql(dialect="snowflake", pretty=pretty, unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as exc:
        t.note("UNSUPPORTED", "manual", _first_line(exc))
        return t
    try:
        sqlglot.parse_one(output, read="snowflake", error_level=ErrorLevel.RAISE)
    except ParseError as exc:
        t.note("VERIFY", "manual", f"generated SQL does not parse as Snowflake: {_first_line(exc)}")
        return t
    t.output = output
    return t


def _manual(t: Translation) -> bool:
    return t.status == "manual"


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:200]


@dataclass
class FileResult:
    path: str
    dialect: str
    translations: list[Translation] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)

    def script(self) -> str:
        """The translated script, with notes as comments next to each statement."""
        chunks = [f"-- Translated from {self.dialect} by sfmigrate: {self.path}"]
        for line, t in zip(self.lines, self.translations, strict=True):
            header = f"-- [{t.status}] line {line}"
            notes = [f"--   {n.severity}: {n.rule}: {n.message}" for n in t.notes]
            if t.status == "manual":
                body = "\n".join("-- " + s for s in t.source.splitlines())
            elif t.dropped or not t.output:
                body = ""
            else:
                body = t.output + ";"
            chunks.append("\n".join([header, *notes, body]).rstrip())
        return "\n\n".join(chunks) + "\n"


def translate_text(script: str, dialect: str, path: str = "<text>", *, pretty: bool = True) -> FileResult:
    result = FileResult(path=path, dialect=dialect)
    for piece in split(script, dialect):
        if piece.kind == "bteq":
            t = Translation(dialect=dialect, source=piece.text, kind="bteq", dropped=True)
            t.note("TD001", "info", f"BTEQ command {piece.text.split()[0]} dropped: move control flow to the orchestrator")
            if piece.text.upper().startswith((".IF", ".GOTO", ".LABEL", ".RUN")):
                t.note(
                    "TD001",
                    "warning",
                    "BTEQ control flow (.IF/.GOTO) changes what runs: rebuild it in the orchestrator",
                )
        elif piece.kind == "plsql":
            t = Translation(dialect=dialect, source=piece.text, kind="plsql")
            t.note("OR008", "manual", "PL/SQL needs a rewrite in Snowflake Scripting or the application")
        else:
            t = translate_statement(piece.text, dialect, pretty=pretty)
        result.translations.append(t)
        result.lines.append(piece.line)
    return result


def detect_dialect(path: Path, default: str | None = None) -> str:
    parts = {p.lower() for p in path.parts}
    for dialect in DIALECTS:
        if dialect in parts:
            return dialect
    if path.suffix.lower() in (".bteq", ".btq"):
        return "teradata"
    if path.suffix.lower() in (".pls", ".pks", ".pkb"):
        return "oracle"
    if default:
        return default
    raise ValueError(f"cannot tell the dialect of {path}; pass --dialect")
