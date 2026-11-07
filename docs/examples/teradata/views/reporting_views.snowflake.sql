-- Translated from teradata by sfmigrate: teradata/views/reporting_views.sql

-- [auto] line 1
--   info: TD010: TITLE display attributes were dropped; use column aliases if they matter
CREATE OR REPLACE VIEW sales.v_latest_order AS
SELECT
  customer_id,
  order_id,
  amount
FROM sales.orders
QUALIFY
  ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ordered_at DESC NULLS LAST) = 1;

-- [auto] line 6
CREATE OR REPLACE VIEW sales.v_top_customers AS
SELECT
  c.customer_id,
  c.name,
  SUM(o.amount) AS total
FROM sales.customers AS c
JOIN sales.orders AS o
  ON o.customer_id = c.customer_id
WHERE
  o.ordered_at >= ADD_MONTHS(CURRENT_DATE, -12)
GROUP BY
  c.customer_id,
  c.name
ORDER BY
  total DESC NULLS LAST
LIMIT 100;

-- [auto] line 14
--   info: TD008: INDEX(string, substring) became CHARINDEX(substring, string)
CREATE OR REPLACE VIEW sales.v_contact_domains AS
SELECT
  customer_id,
  SUBSTRING(email, CHARINDEX('@', email) + 1) AS domain,
  ZEROIFNULL(score) AS score
FROM crm.contacts
WHERE
  email LIKE ANY ('%@example.com', '%@example.org');
