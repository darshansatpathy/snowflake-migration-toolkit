# ADR-0001: sqlglot for parsing and generation, our own rules for meaning

**Status:** accepted

## Context

Writing a Teradata and an Oracle parser is years of work. sqlglot parses both and generates
Snowflake SQL. Probing it with the constructs that matter in real migrations showed it is right
most of the time, and wrong in ways that do not raise errors: Oracle `DATE` becomes `DATE` and
loses the time of day, unbounded `NUMBER` becomes `NUMBER(38,0)` and loses decimals, `ROWNUM`
and `SYSTIMESTAMP` pass through untranslated.

## Decision

Use sqlglot for parsing and generation, and put a rule layer around it that fixes what the
transpiler misses and records a note for every change. Rules run on the text before parsing
(for syntax sqlglot cannot parse) and on the tree before generation.

## Consequences

- The rules are small and testable, and their value is visible: the README lists what each one
  prevents.
- A sqlglot upgrade can change outputs. The corpus catches that: any change in output, status
  or rules fails CI and has to be reviewed.
