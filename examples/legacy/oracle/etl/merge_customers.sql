MERGE INTO customers t
USING staging_customers s
ON (t.customer_id = s.customer_id)
WHEN MATCHED THEN UPDATE SET t.name = s.name, t.segment = NVL(s.segment, t.segment)
WHEN NOT MATCHED THEN INSERT (customer_id, name, segment) VALUES (s.customer_id, s.name, s.segment);

-- Rows loaded without notes
SELECT order_id FROM orders WHERE notes = '';

INSERT INTO audit_log (event, at) VALUES ('customers merged', SYSTIMESTAMP);
