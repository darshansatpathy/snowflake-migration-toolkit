REPLACE MACRO sales.close_old_orders (cutoff DATE) AS (
    UPDATE sales.orders SET status = 'closed' WHERE ordered_at < :cutoff;
);
