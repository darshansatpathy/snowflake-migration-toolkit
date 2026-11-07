-- Translated from oracle by sfmigrate: oracle/ddl/schema.sql

-- [auto] line 1
CREATE SEQUENCE orders_seq START WITH 1 INCREMENT BY 1;

-- [assisted] line 3
--   info: OR010: LOB column mapped to VARCHAR/BINARY: check values fit Snowflake's size limits
--   warning: OR003: SYSDATE is the database host's local time in Oracle, UTC in Snowflake: check the session time zone
--   warning: OR006: NUMBER without precision became NUMBER(38, 10); confirm the scale the data needs
--   info: OR004: Oracle DATE became TIMESTAMP_NTZ(0): Oracle DATE values carry a time of day
CREATE TABLE orders (
  order_id DECIMAL(10) NOT NULL,
  customer_id DECIMAL(10) NOT NULL,
  amount DECIMAL(12, 2),
  discount DECIMAL(38, 10),
  status VARCHAR(20),
  created TIMESTAMPNTZ(0) DEFAULT SYSDATE(),
  notes VARCHAR
);

-- [auto] line 13
--   info: OR004: Oracle DATE became TIMESTAMP_NTZ(0): Oracle DATE values carry a time of day
CREATE TABLE employees (
  employee_id DECIMAL(6) NOT NULL,
  manager_id DECIMAL(6),
  name VARCHAR(100),
  hired TIMESTAMPNTZ(0)
);
