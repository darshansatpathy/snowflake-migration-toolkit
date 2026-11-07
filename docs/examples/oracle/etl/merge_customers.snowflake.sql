-- Translated from oracle by sfmigrate: oracle/etl/merge_customers.sql

-- [auto] line 1
MERGE INTO customers AS t
USING staging_customers AS s
ON (
  t.customer_id = s.customer_id
)
WHEN MATCHED THEN UPDATE SET
  t.name = s.name,
  t.segment = COALESCE(s.segment, t.segment)
WHEN NOT MATCHED THEN INSERT (customer_id, name, segment) VALUES (s.customer_id, s.name, s.segment);

-- [assisted] line 7
--   warning: OR007: '' is NULL in Oracle but an empty string in Snowflake: comparisons and NVL behave differently
/* Rows loaded without notes */
SELECT
  order_id
FROM orders
WHERE
  notes = '';

-- [auto] line 10
--   info: OR003: SYSTIMESTAMP became CURRENT_TIMESTAMP()
INSERT INTO audit_log (
  event,
  at
)
VALUES
  ('customers merged', CURRENT_TIMESTAMP());
