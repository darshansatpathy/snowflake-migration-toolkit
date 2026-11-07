CREATE OR REPLACE PROCEDURE refresh_summary AS
BEGIN
  DELETE FROM order_summary;
  INSERT INTO order_summary (month, total)
  SELECT TRUNC(created, 'MM'), SUM(amount) FROM orders GROUP BY TRUNC(created, 'MM');
  COMMIT;
END;
/
