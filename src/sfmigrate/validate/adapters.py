"""Database adapters: column metadata, aggregates and key-ordered row streams.

PostgreSQL, DuckDB and SQLite are exercised by the tests. Snowflake, Oracle and Teradata use
the same interface through their DB-API drivers (optional extras) and are not run in CI.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    precision: int | None = None
    scale: int | None = None
    length: int | None = None


class AdapterError(RuntimeError):
    pass


def _ident(name: str) -> str:
    parts = name.split(".")
    for part in parts:
        if not IDENT.match(part):
            raise AdapterError(f"unsafe identifier {name!r}: use plain names (letters, digits, _ and $)")
    return ".".join(parts)


class Adapter:
    engine = "generic"
    text_order = ""  # appended to text keys in ORDER BY for a byte-wise order

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    def _cursor(self) -> Any:
        return self.conn.cursor()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        cur = self._cursor()
        cur.execute(sql, params) if params else cur.execute(sql)
        return [tuple(r) for r in cur.fetchall()]

    def columns(self, table: str) -> list[Column]:
        schema, name = self._split(table)
        rows = self.query(
            "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale, character_maximum_length "
            "FROM information_schema.columns WHERE lower(table_name) = lower(?) "
            + ("AND lower(table_schema) = lower(?) " if schema else "")
            + "ORDER BY ordinal_position",
            (name, schema) if schema else (name,),
        )
        return [Column(r[0], str(r[1]).lower(), str(r[2]).upper() == "YES", r[3], r[4], r[5]) for r in rows]

    @staticmethod
    def _split(table: str) -> tuple[str | None, str]:
        _ident(table)
        parts = table.split(".")
        return (parts[-2] if len(parts) > 1 else None), parts[-1]

    def count(self, table: str, where: str | None) -> int:
        rows = self.query(f"SELECT count(*) FROM {_ident(table)}" + (f" WHERE {where}" if where else ""))  # noqa: S608
        return int(rows[0][0])

    def aggregates(self, table: str, column: str, numeric: bool, where: str | None) -> dict[str, Any]:
        c = _ident(column)
        parts = [f"count({c})", f"min({c})", f"max({c})"] + ([f"sum({c})"] if numeric else [])
        sql = f"SELECT {', '.join(parts)} FROM {_ident(table)}" + (f" WHERE {where}" if where else "")  # noqa: S608
        row = self.query(sql)[0]
        out = {"non_null": row[0], "min": row[1], "max": row[2]}
        if numeric:
            out["sum"] = row[3]
        return out

    def rows(
        self,
        table: str,
        columns: Sequence[str],
        keys: Sequence[str],
        text_keys: set[str],
        where: str | None,
        batch: int = 5000,
    ) -> Iterator[tuple[Any, ...]]:
        cols = ", ".join(_ident(c) for c in columns)
        order = ", ".join(_ident(k) + (self.text_order if k in text_keys else "") for k in keys)
        sql = f"SELECT {cols} FROM {_ident(table)}" + (f" WHERE {where}" if where else "") + f" ORDER BY {order}"  # noqa: S608
        cur = self._stream_cursor()
        try:
            cur.execute(sql)
            while True:
                chunk = cur.fetchmany(batch)
                if not chunk:
                    break
                for row in chunk:
                    yield tuple(row)
        finally:
            cur.close()

    def _stream_cursor(self) -> Any:
        return self._cursor()


class PostgresAdapter(Adapter):
    engine = "postgresql"
    text_order = ' COLLATE "C"'

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        with self.conn.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), params or None)
            return [tuple(r) for r in cur.fetchall()]

    _streams = 0

    def _stream_cursor(self) -> Any:
        # A server-side cursor streams rows instead of loading the table; WITH HOLD lets it live
        # outside a transaction on this autocommit connection.
        PostgresAdapter._streams += 1
        return self.conn.cursor(name=f"sfmigrate_rows_{PostgresAdapter._streams}", withhold=True)


class DuckDBAdapter(Adapter):
    engine = "duckdb"

    def _cursor(self) -> Any:
        return self.conn.cursor()


class SQLiteAdapter(Adapter):
    engine = "sqlite"

    def columns(self, table: str) -> list[Column]:
        rows = self.query(f"PRAGMA table_info({_ident(table)})")
        out = []
        for r in rows:
            m = re.match(r"([A-Za-z ]+)(?:\((\d+)(?:,\s*(\d+))?\))?", str(r[2]))
            base = (m.group(1).strip() if m else str(r[2])).lower()
            p = int(m.group(2)) if m and m.group(2) else None
            s = int(m.group(3)) if m and m.group(3) else None
            out.append(Column(r[1], base, not r[3], p, s, p if "char" in base else None))
        return out


class SnowflakeAdapter(Adapter):  # pragma: no cover - needs a Snowflake account
    engine = "snowflake"
    text_order = " COLLATE 'utf8'"


class OracleAdapter(Adapter):  # pragma: no cover - needs an Oracle database
    engine = "oracle"

    def columns(self, table: str) -> list[Column]:
        schema, name = self._split(table)
        rows = self.query(
            "SELECT column_name, data_type, nullable, data_precision, data_scale, char_length FROM all_tab_columns "  # noqa: S608
            "WHERE table_name = upper(:1)" + (" AND owner = upper(:2)" if schema else "") + " ORDER BY column_id",
            (name, schema) if schema else (name,),
        )
        return [Column(r[0].lower(), r[1].lower(), r[2] == "Y", r[3], r[4], r[5]) for r in rows]


class TeradataAdapter(Adapter):  # pragma: no cover - needs a Teradata system
    engine = "teradata"


def connect(url: str) -> Adapter:
    """Open an adapter from a URL: postgresql://, duckdb:///path, sqlite:///path, snowflake://, oracle://, teradata://."""
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0]
    if scheme in ("postgresql", "postgres"):
        import psycopg

        return PostgresAdapter(psycopg.connect(url, autocommit=True, options="-c TimeZone=UTC"))
    if scheme == "duckdb":
        import duckdb

        path = unquote(parsed.path)[1:] if parsed.path.startswith("/") else parsed.path
        conn = duckdb.connect(path or ":memory:", read_only=False)
        conn.execute("SET TimeZone = 'UTC'")
        return DuckDBAdapter(conn)
    if scheme == "sqlite":
        return SQLiteAdapter(sqlite3.connect(unquote(parsed.path)[1:] or ":memory:"))
    if scheme == "snowflake":  # pragma: no cover
        import snowflake.connector

        db, _, schema = parsed.path.strip("/").partition("/")
        return SnowflakeAdapter(
            snowflake.connector.connect(
                user=parsed.username,
                password=unquote(parsed.password or ""),
                account=parsed.hostname,
                database=db or None,
                schema=schema or None,
            )
        )
    if scheme == "oracle":  # pragma: no cover
        import oracledb

        return OracleAdapter(
            oracledb.connect(
                user=parsed.username,
                password=unquote(parsed.password or ""),
                dsn=f"{parsed.hostname}:{parsed.port or 1521}{parsed.path}",
            )
        )
    if scheme == "teradata":  # pragma: no cover
        import teradatasql

        return TeradataAdapter(teradatasql.connect(host=parsed.hostname, user=parsed.username, password=unquote(parsed.password or "")))
    raise AdapterError(f"unsupported database URL scheme {scheme!r}")
