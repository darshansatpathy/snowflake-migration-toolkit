# Migration assessment

8 files, 33 statements. **92%** translate without a rewrite (16 automatic, 8 needing review); 2 need a person; 7 are dropped on purpose.

Estimated effort: **12.8 hours** (auto 0.05h, assisted 0.5h, manual 4.0h per statement; calibrate after a pilot).

| File | Dialect | Statements | Auto | Assisted | Manual | Dropped |
|---|---|---|---|---|---|---|
| oracle/ddl/schema.sql | oracle | 3 | 2 | 1 | 0 | 0 |
| oracle/etl/merge_customers.sql | oracle | 3 | 2 | 1 | 0 | 0 |
| oracle/plsql/refresh_summary.sql | oracle | 1 | 0 | 0 | 1 | 0 |
| oracle/queries/reports.sql | oracle | 5 | 3 | 2 | 0 | 0 |
| teradata/bteq/daily_load.bteq | teradata | 13 | 6 | 2 | 0 | 5 |
| teradata/ddl/sales_tables.sql | teradata | 4 | 0 | 2 | 0 | 2 |
| teradata/macros/close_orders.sql | teradata | 1 | 0 | 0 | 1 | 0 |
| teradata/views/reporting_views.sql | teradata | 3 | 3 | 0 | 0 | 0 |

## What the rules found

| Rule | What | Statements |
|---|---|---|
| OR001 | ROWNUM | 2 |
| OR002 | (+) outer joins | 1 |
| OR003 | SYSDATE and SYSTIMESTAMP | 3 |
| OR004 | DATE type | 2 |
| OR006 | NUMBER without precision | 1 |
| OR007 | Empty strings | 1 |
| OR008 | PL/SQL | 1 |
| OR009 | CONNECT BY | 1 |
| OR010 | LOB types | 1 |
| OR011 | Date arithmetic | 1 |
| TD001 | BTEQ commands | 8 |
| TD002 | SET / MULTISET tables | 2 |
| TD003 | Physical table options | 3 |
| TD004 | Primary and secondary indexes | 2 |
| TD005 | Column attributes | 6 |
| TD006 | Volatile tables | 2 |
| TD007 | COLLECT STATISTICS | 3 |
| TD008 | INDEX(string, substring) | 1 |
| TD009 | UPDATE ... FROM | 1 |
| TD010 | TITLE phrase in queries | 1 |
| TD012 | Macros, procedures, temporal SQL | 1 |
| TD013 | DATABASE statement | 1 |

## Needs a person

| Where | What | Why |
|---|---|---|
| oracle/plsql/refresh_summary.sql:1 | plsql | PL/SQL needs a rewrite in Snowflake Scripting or the application |
| teradata/macros/close_orders.sql:1 | statement | macros, stored procedures and temporal SQL need to be rewritten by hand |
