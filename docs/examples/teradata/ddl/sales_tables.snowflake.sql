-- Translated from teradata by sfmigrate: teradata/ddl/sales_tables.sql

-- [assisted] line 1
--   info: TD002: MULTISET dropped: Snowflake tables allow duplicate rows like MULTISET
--   info: TD003: physical option fallbackproperty dropped
--   info: TD003: physical option journalproperty dropped
--   info: TD004: PRIMARY INDEX dropped: distribution is automatic; consider CLUSTER BY for large tables
--   info: TD005: status: characterset attribute dropped
--   warning: TD005: status: NOT CASESPECIFIC became COLLATE 'en-ci'; comparisons stay case-insensitive
--   info: TD005: ship_date: dateformat attribute dropped
/* Sales subject area (Teradata) */
CREATE TABLE sales.orders (
  order_id INT NOT NULL,
  customer_id INT NOT NULL,
  status VARCHAR(20) COLLATE 'en-ci',
  amount DECIMAL(12, 2),
  ordered_at TIMESTAMP(0),
  ship_date DATE
);

-- [assisted] line 13
--   warning: TD002: SET table: Teradata silently discarded duplicate rows; deduplicate on load
--   info: TD003: physical option fallbackproperty dropped
--   warning: TD004: UNIQUE index dropped: Snowflake does not enforce uniqueness; check it on load
--   info: TD005: name: characterset attribute dropped
--   info: TD005: segment: compress attribute dropped
--   info: TD005: created: dateformat attribute dropped
CREATE TABLE sales.customers (
  customer_id INT NOT NULL,
  name VARCHAR(100),
  segment CHAR(2),
  created DATE
);

-- [dropped] line 22
--   info: TD007: COLLECT STATISTICS dropped: Snowflake maintains statistics automatically

-- [dropped] line 23
--   info: TD007: COLLECT STATISTICS dropped: Snowflake maintains statistics automatically
