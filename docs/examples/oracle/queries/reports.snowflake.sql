-- Translated from oracle by sfmigrate: oracle/queries/reports.sql

-- [auto] line 1
--   info: OR002: (+) outer join rewritten to ANSI LEFT JOIN
/* Monthly order report */
SELECT
  TO_CHAR(o.created, 'YYYY-MM') AS month,
  COALESCE(c.segment, 'unknown') AS segment,
  DECODE(o.status, 'O', 'open', 'C', 'closed', 'other') AS status,
  SUM(o.amount) AS total
FROM orders AS o
LEFT JOIN customers AS c
  ON o.customer_id = c.customer_id
WHERE
  o.created >= DATE('2024-01-01', 'yyyy-mm-DD')
GROUP BY
  TO_CHAR(o.created, 'YYYY-MM'),
  COALESCE(c.segment, 'unknown'),
  DECODE(o.status, 'O', 'open', 'C', 'closed', 'other');

-- [assisted] line 11
--   info: OR001: WHERE ROWNUM <= 100 became LIMIT 100
--   warning: OR003: SYSDATE is the database host's local time in Oracle, UTC in Snowflake: check the session time zone
--   info: OR011: date +/- n became DATEADD(DAY, n, ...)
/* Last 30 days, first 100 rows */
SELECT
  order_id,
  amount
FROM orders
WHERE
  created > DATEADD(DAY, -30, SYSDATE())
LIMIT 100;

-- [assisted] line 14
--   warning: OR001: ROWNUM with ORDER BY: Oracle limits before sorting, kept with a subquery; confirm that was intended
SELECT
  *
FROM (
  /* Biggest ten recent orders (Oracle applies ROWNUM before ORDER BY) */
  SELECT
    order_id,
    amount
  FROM orders
  LIMIT 10
) AS limited
ORDER BY
  amount DESC;

-- [auto] line 17
--   info: OR009: CONNECT BY kept: Snowflake supports it; a recursive CTE is the portable alternative
/* Reporting lines */
SELECT
  employee_id,
  manager_id,
  LEVEL AS depth
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR employee_id = manager_id;

-- [auto] line 23
/* Customers without orders */
SELECT
  customer_id
FROM customers
EXCEPT
SELECT
  customer_id
FROM orders;
