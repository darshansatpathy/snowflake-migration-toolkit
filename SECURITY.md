# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/darshansatpathy/snowflake-migration-toolkit/security/advisories/new)
for this repository. You should get an acknowledgement within three working days.

## Scope

The translator reads SQL files and writes SQL files; it never connects to a database. The
validator connects to the source and target named in its config and runs only `SELECT`
statements and metadata queries.

## Operating it safely

- Give the validator read-only accounts on both sides.
- Pass credentials through environment variables or a secrets manager, not committed configs.
- Table and column names in validation configs are checked against a plain-identifier pattern
  before they reach SQL; `where:` filters are passed through as written, so treat validation
  configs as code and review them.
- Translated SQL is a proposal. Review it, especially anything marked assisted, before running
  it against production.
