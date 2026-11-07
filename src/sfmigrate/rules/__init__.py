"""Translation rules, by source dialect.

Each rule fixes something sqlglot's transpiler does not do, or does in a way that changes
meaning on Snowflake, and records a note. Rules run in two places: on the statement text before
parsing (for syntax sqlglot cannot parse), and on the parsed tree before generating Snowflake SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlglot import exp

from sfmigrate.model import Translation

TextRule = Callable[[str, Translation], str]
TreeRule = Callable[[exp.Expression, Translation], exp.Expression]


@dataclass(frozen=True)
class RuleInfo:
    id: str
    dialect: str
    title: str
    effect: str


CATALOG: list[RuleInfo] = []


def describe(id: str, dialect: str, title: str, effect: str) -> None:
    CATALOG.append(RuleInfo(id, dialect, title, effect))
