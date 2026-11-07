# ADR-0004: A reviewed corpus is the specification

**Status:** accepted

## Context

There is no Teradata, Oracle or Snowflake in CI, so translations cannot be executed on both
sides there.

## Decision

Keep a corpus of real constructs, each with the Snowflake output, status and rules that were
reviewed against the vendors' documentation. CI requires an exact match. The validator is
evaluated separately with defects planted in real data on real engines (PostgreSQL to DuckDB).

## Consequences

- A change in behaviour is always visible and always reviewed.
- The corpus proves consistency with reviewed expectations, not execution on Snowflake; the
  README says so.
