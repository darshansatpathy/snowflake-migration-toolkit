-- Translated from teradata by sfmigrate: teradata/macros/close_orders.sql

-- [manual] line 1
--   manual: TD012: macros, stored procedures and temporal SQL need to be rewritten by hand
-- REPLACE MACRO sales.close_old_orders (cutoff DATE) AS (
--     UPDATE sales.orders SET status = 'closed' WHERE ordered_at < :cutoff;
-- )
