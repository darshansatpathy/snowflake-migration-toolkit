-- Translated from teradata by sfmigrate: teradata/bteq/daily_load.bteq

-- [dropped] line 1
--   info: TD001: BTEQ command .LOGON dropped: move control flow to the orchestrator

-- [dropped] line 2
--   info: TD001: BTEQ command .SET dropped: move control flow to the orchestrator

-- [auto] line 4
--   info: TD013: DATABASE became USE SCHEMA: a Teradata database maps to a Snowflake schema
USE SCHEMA sales;

-- [auto] line 6
--   info: TD006: VOLATILE table became TEMPORARY (session-scoped in both)
--   info: TD006: ON COMMIT PRESERVE ROWS dropped: Snowflake temporary tables keep rows for the session
CREATE TEMPORARY TABLE vt_new_orders AS
(
  SELECT
    order_id,
    customer_id,
    status,
    amount,
    ordered_at
  FROM staging.orders_raw
  WHERE
    loaded = 0
);

-- [assisted] line 12
--   info: TD001: BTEQ command .IF dropped: move control flow to the orchestrator
--   warning: TD001: BTEQ control flow (.IF/.GOTO) changes what runs: rebuild it in the orchestrator

-- [auto] line 14
INSERT INTO sales.orders (
  order_id,
  customer_id,
  status,
  amount,
  ordered_at
)
SELECT
  order_id,
  customer_id,
  status,
  amount,
  ordered_at
FROM vt_new_orders;

-- [auto] line 17
--   info: TD009: Teradata UPDATE ... FROM rewritten to Snowflake's UPDATE ... SET ... FROM
UPDATE sales.orders AS t SET amount = f.amount
FROM staging.order_fixes AS f
WHERE
  t.order_id = f.order_id;

-- [auto] line 21
MERGE INTO sales.customers AS t
USING staging.customers AS s
ON t.customer_id = s.customer_id
WHEN MATCHED THEN UPDATE SET
  name = s.name
WHEN NOT MATCHED THEN INSERT (customer_id, name) VALUES (s.customer_id, s.name);

-- [auto] line 27
DELETE FROM staging.orders_raw
WHERE
  loaded = 0;

-- [dropped] line 29
--   info: TD007: COLLECT STATISTICS dropped: Snowflake maintains statistics automatically

-- [assisted] line 31
--   info: TD001: BTEQ command .IF dropped: move control flow to the orchestrator
--   warning: TD001: BTEQ control flow (.IF/.GOTO) changes what runs: rebuild it in the orchestrator

-- [dropped] line 32
--   info: TD001: BTEQ command .LOGOFF dropped: move control flow to the orchestrator

-- [dropped] line 33
--   info: TD001: BTEQ command .QUIT dropped: move control flow to the orchestrator
