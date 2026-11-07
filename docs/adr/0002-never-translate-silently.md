# ADR-0002: Never translate silently

**Status:** accepted

## Context

The costly translation error is not the one that fails to run. It is the one that runs and
means something else, discovered months later in a report that does not match.

## Decision

Every statement gets a status (auto, assisted, manual, dropped) and every change gets a note.
Where Snowflake behaves differently and we cannot prove the intent (`''` versus NULL, `SYSDATE`
time zones, `ROWNUM` with `ORDER BY`, `CAST ... FORMAT`), the statement is translated faithfully
and marked *assisted* rather than rewritten into what we guess was meant. What cannot be
translated faithfully is *manual*, with the reason, and its source is kept as comments in the
output.

## Consequences

- Reviewers see exactly which statements need them, and why.
- Some *assisted* statements will turn out to be fine. That review cost is the price of not
  shipping silent changes.
