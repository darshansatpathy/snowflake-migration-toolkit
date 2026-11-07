-- Monthly order report
SELECT TO_CHAR(o.created, 'YYYY-MM') AS month,
       NVL(c.segment, 'unknown') AS segment,
       DECODE(o.status, 'O', 'open', 'C', 'closed', 'other') AS status,
       SUM(o.amount) AS total
FROM orders o, customers c
WHERE o.customer_id = c.customer_id(+)
  AND o.created >= TO_DATE('2024-01-01', 'YYYY-MM-DD')
GROUP BY TO_CHAR(o.created, 'YYYY-MM'), NVL(c.segment, 'unknown'), DECODE(o.status, 'O', 'open', 'C', 'closed', 'other');

-- Last 30 days, first 100 rows
SELECT order_id, amount FROM orders WHERE created > SYSDATE - 30 AND ROWNUM <= 100;

-- Biggest ten recent orders (Oracle applies ROWNUM before ORDER BY)
SELECT order_id, amount FROM orders WHERE ROWNUM <= 10 ORDER BY amount DESC;

-- Reporting lines
SELECT employee_id, manager_id, LEVEL AS depth
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR employee_id = manager_id;

-- Customers without orders
SELECT customer_id FROM customers MINUS SELECT customer_id FROM orders;
