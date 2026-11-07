REPLACE VIEW sales.v_latest_order AS
SELECT customer_id, order_id (TITLE 'Latest order'), amount (TITLE 'Amount EUR')
FROM sales.orders
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ordered_at DESC) = 1;

REPLACE VIEW sales.v_top_customers AS
SELECT TOP 100 c.customer_id, c.name, SUM(o.amount) AS total
FROM sales.customers c
JOIN sales.orders o ON o.customer_id = c.customer_id
WHERE o.ordered_at >= ADD_MONTHS(CURRENT_DATE, -12)
GROUP BY c.customer_id, c.name
ORDER BY total DESC;

REPLACE VIEW sales.v_contact_domains AS
SELECT customer_id, SUBSTR(email, INDEX(email, '@') + 1) AS domain, ZEROIFNULL(score) AS score
FROM crm.contacts
WHERE email LIKE ANY ('%@example.com', '%@example.org');
