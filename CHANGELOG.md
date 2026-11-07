# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-07

### Added

- Statement splitter for Teradata (BTEQ commands, procedures) and Oracle (PL/SQL blocks).
- Translation to Snowflake with sqlglot and 24 rules for what it misses, each change recorded
  as a note; statuses auto, assisted, manual and dropped; Snowflake re-parse check.
- Assessment: inventory, automation rate, effort estimate, Markdown/JSON/CSV reports, and
  annotated translated scripts per file.
- Row-level validation: schema, counts, aggregates and a streaming merge of every row, with
  explicit normalization rules; adapters for PostgreSQL, DuckDB and SQLite, plus Snowflake,
  Oracle and Teradata through their drivers.
- A 53-case reviewed translation corpus and 14 injected-defect validation scenarios, both
  enforced in CI.
