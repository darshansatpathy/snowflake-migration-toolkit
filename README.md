# Snowflake Migration Toolkit

[![CI](https://github.com/darshansatpathy/snowflake-migration-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/darshansatpathy/snowflake-migration-toolkit/actions/workflows/ci.yml)
[![CodeQL](https://github.com/darshansatpathy/snowflake-migration-toolkit/actions/workflows/codeql.yml/badge.svg)](https://github.com/darshansatpathy/snowflake-migration-toolkit/actions/workflows/codeql.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Corpus](https://img.shields.io/badge/translation%20corpus-53%2F53-success)
![Defects caught](https://img.shields.io/badge/injected%20defects%20caught-11%2F11-success)
![License](https://img.shields.io/badge/license-MIT-green)

**Teradata and Oracle to Snowflake: an assessment of what a codebase contains, SQL
translation that says exactly what it changed and what it could not do, and row-level
validation that proves the migrated data matches.**

A migration fails in two quiet ways. SQL that translates without errors but means something
else on Snowflake, and data that loads without errors but is not the data that was there before.
This toolkit is built around catching both.

```
legacy SQL ─▶ split ─▶ sqlglot + rules ─▶ Snowflake SQL with review notes ─▶ parses as Snowflake?
                         │
                         └─▶ assessment: auto / assisted / manual / dropped, effort estimate

source table ─▶ normalize ─┐
                           ├─▶ schema, counts, aggregates, every row in key order ─▶ report, exit code
target table ─▶ normalize ─┘
```

## Why the rules exist

The translation engine is [sqlglot](https://github.com/tobymao/sqlglot). On its own, several of its
Teradata and Oracle outputs run on Snowflake but give different results, or do not run at all.
The rules fix those, and every change is written next to the statement it touched:

| Source | sqlglot alone | With the rules |
|---|---|---|
| Oracle `created DATE` | `created DATE`: **the time of day is lost** | `created TIMESTAMP_NTZ(0)`: Oracle DATE carries a time |
| Oracle `amount NUMBER` | `DECIMAL`, which is `NUMBER(38,0)`: **decimals truncated** | `NUMBER(38,10)`, flagged to confirm the scale |
| Oracle `TO_DATE(s, 'YYYY-MM-DD HH24:MI')` | `DATE(s, ...)`: **time dropped** | `TO_TIMESTAMP(s, ...)` |
| Oracle `SYSDATE - 30` | `SYSDATE() - 30`: fails on a timestamp | `DATEADD(DAY, -30, SYSDATE())`, plus a time-zone warning |
| Oracle `WHERE ROWNUM <= 10` | unchanged: Snowflake has no ROWNUM | `LIMIT 10`; with ORDER BY, a subquery that keeps Oracle's limit-then-sort meaning |
| Oracle `SYSTIMESTAMP` | `SYSTIMESTAMP()`: not a Snowflake function | `CURRENT_TIMESTAMP()` |
| Oracle `a = b(+)` | kept | ANSI `LEFT JOIN` |
| Oracle `WHERE notes = ''` | kept silently | kept, and flagged: `''` is NULL in Oracle, not in Snowflake |
| Teradata `CREATE MULTISET TABLE ... PRIMARY INDEX` | error | clean DDL; a `SET` table or `UNIQUE` index is flagged because Snowflake will not enforce it |
| Teradata `NOT CASESPECIFIC` | error | `COLLATE 'en-ci'`, so comparisons stay case-insensitive |
| Teradata `UPDATE t FROM a, b SET ...` | parse error | `UPDATE a SET ... FROM b ...` |
| Teradata `INDEX(email, '@')` | unchanged: not a Snowflake function | `CHARINDEX('@', email)` |
| Teradata `(TITLE 'x')`, `COLLECT STATISTICS`, BTEQ `.LOGON` | errors | dropped, with a note; BTEQ `.IF ERRORCODE` is flagged because it changes what runs |
| Macros, procedures, PL/SQL, `NORMALIZE` | errors | **not translated**: reported as manual with the reason |

The full list: `sfmigrate rules`. Each statement ends in one of four states:

- **auto**: translated, nothing to review;
- **assisted**: translated, with warnings a person should check;
- **manual**: not translated, with the reason;
- **dropped**: removed on purpose, such as `COLLECT STATISTICS`.

Output is accepted only if it parses back as Snowflake.

## Try it

```bash
pip install -e ".[dev]"
sfmigrate sql --dialect oracle "SELECT * FROM orders WHERE created > SYSDATE - 30 AND ROWNUM <= 100"
```
```sql
-- [assisted]
-- info: OR001: WHERE ROWNUM <= 100 became LIMIT 100
-- warning: OR003: SYSDATE is the database host's local time in Oracle, UTC in Snowflake: check the session time zone
-- info: OR011: date +/- n became DATEADD(DAY, n, ...)
SELECT * FROM orders WHERE created > DATEADD(DAY, -30, SYSDATE()) LIMIT 100;
```

```bash
sfmigrate assess examples/legacy                        # inventory, automation rate, effort, what needs a person
sfmigrate translate examples/legacy --out snowflake/    # one annotated .snowflake.sql per file + assessment
sfmigrate validate examples/validation.yaml             # row-level comparison, exit code 1 on any difference
```

[examples/legacy](examples/legacy) is a small mixed codebase: Teradata DDL, a BTEQ load job,
reporting views and a macro; Oracle DDL, reports, an ETL merge and a PL/SQL procedure. Its
assessment ([docs/examples/assessment.md](docs/examples/assessment.md)) finds 33 statements in
8 files. 92% translate without a rewrite (16 automatic, 8 needing review), 2 need a person, and
7 are dropped on purpose, for an estimated 12.8 hours. Every translated script is in
[docs/examples](docs/examples), and CI fails if they drift from what the code produces.

## Validation

```yaml
source: postgresql://...                  # or oracle://, teradata://, sqlite:///...
target: snowflake://user:pw@account/DB/SCHEMA   # or duckdb:///...
tables:
  - name: orders
    source: legacy.orders
    target: analytics.orders
    key: [order_id]
    rules: {trim_trailing: true, empty_as_null: true}   # CHAR padding; Oracle '' is NULL
    source_rules: {timestamp_timezone: Asia/Kolkata}    # the source stored local time
```

For each table:

- **Schema:** columns missing or extra, type families, lost scale, shorter strings, dropped NOT NULL.
- **Totals:** row counts, and per-column count, min, max and sum.
- **Rows:** every row, streamed from both sides in key order and merged, so memory stays flat.
  The report lists what is missing, extra, changed (with the columns and both values) and
  duplicated.

Text keys are ordered byte-wise on both engines so the merge lines up. If they still disagree,
the comparison falls back to holding the keys in memory and says so.

Normalization is explicit and off by default. Each rule exists because a real migration produces
differences that are not defects: CHAR padding, `''` versus NULL, local versus UTC timestamps,
float noise. Nothing is hidden unless a config says so.

## Results

From `sfmigrate eval`, run in CI against PostgreSQL 17 and DuckDB on every push.

**Translation corpus.** [53 reviewed cases](corpus/cases.yaml): 53 / 53 exact (39 automatic,
9 assisted, 4 manual, 1 dropped). Rules changed or flagged 27 of them. Each expected output was
checked against Snowflake's semantics before being frozen; CI fails if any output, status or
rule set changes.

**Validation against injected defects.** 20,000 rows created in PostgreSQL, copied into DuckDB
the way a migration copies them (padding trimmed, NULLs written as `''`, timestamps converted to
UTC), then one defect planted per scenario:

| Scenario | Verdict | What it reported |
|---|---|---|
| Faithful copy, with the migration's rules | **pass** | 0 differences |
| The same copy without rules | fail | 20,000 rows "changed": the false alarms the rules remove |
| Seven rows never loaded | fail | 7 missing, row count |
| Three rows loaded twice | fail | 3 duplicate keys |
| Four rows not in the source | fail | 4 extra |
| One amount off by 0.50 | fail | 1 changed, amount aggregates |
| DECIMAL(12,4) created as DECIMAL(12,2) | fail | type check (scale), 19,795 changed |
| DOUBLE within a 0.000001 tolerance | **pass** | 0 differences |
| Timestamps not converted to UTC | fail | 20,000 changed |
| Timestamp created as DATE | fail | type check, 20,000 changed |
| Five statuses lost | fail | 5 changed |
| Statuses truncated to four characters | fail | 10,003 changed |
| A column never created | fail | column check |
| Statuses upper-cased | fail | 20,000 changed |

**11 / 11 defects caught, 0 false alarms on the clean copy.** Each 20,000-row comparison
(schema, aggregates and every row) takes about a quarter of a second.

**What these numbers do not show.** The corpus checks that translations match reviewed
expectations, not that they were executed on Snowflake. The validator's PostgreSQL, DuckDB and
SQLite adapters are tested; its Snowflake, Oracle and Teradata adapters use the same code
through their drivers but have not been run here, because CI has no accounts for them.

## Engineering

- 29 tests, 95% line coverage (gate: 90%), with validation tested on PostgreSQL and DuckDB.
- `ruff`, `mypy --strict`, Python 3.11 to 3.13.
- CI:
  - the evaluation gate;
  - a drift check on the example translations;
  - a wheel install outside the repository that runs the corpus;
  - CodeQL, pip-audit and Dependabot.
- Design notes: [architecture](docs/architecture.md), [the decision records](docs/adr).

## Layout

```
src/sfmigrate/
  splitter.py      scripts to statements: quotes, comments, BTEQ commands, PL/SQL and procedure blocks
  translator.py    sqlglot plus the rules; statuses; Snowflake re-parse check
  rules/           teradata.py, oracle.py: what sqlglot misses, each change recorded as a note
  assess.py        inventory, automation rate, effort, Markdown/JSON/CSV
  validate/        adapters (PostgreSQL, DuckDB, SQLite; Snowflake, Oracle, Teradata via drivers),
                   normalization, schema/aggregate/row comparison, reports
  evaluation.py    corpus gate and injected-defect scenarios
corpus/            reviewed translation cases
examples/          a legacy codebase and a validation config
docs/examples/     what sfmigrate produces from examples/legacy
```

## Known limits

- Stored procedures, macros, PL/SQL and temporal SQL are reported, not translated. They are
  usually a small share of statements and a large share of effort, which the assessment shows.
- Translation is per statement. It does not follow types across statements, so a rule that
  depends on a column's type (Oracle date arithmetic on a column, for example) warns instead of
  rewriting.
- The validator compares values client-side. That keeps one comparison logic across engines,
  at the cost of moving every row over the network once per side; for very large tables, run it
  per partition with `where:`.

## License

MIT. See [LICENSE](LICENSE).
