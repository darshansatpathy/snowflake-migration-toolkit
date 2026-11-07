-- Sales subject area (Teradata)
CREATE MULTISET TABLE sales.orders, NO FALLBACK, NO BEFORE JOURNAL, NO AFTER JOURNAL
(
    order_id     INTEGER NOT NULL,
    customer_id  INTEGER NOT NULL,
    status       VARCHAR(20) CHARACTER SET LATIN NOT CASESPECIFIC,
    amount       DECIMAL(12,2),
    ordered_at   TIMESTAMP(0),
    ship_date    DATE FORMAT 'YYYY-MM-DD'
)
PRIMARY INDEX (order_id);

CREATE SET TABLE sales.customers, NO FALLBACK
(
    customer_id  INTEGER NOT NULL,
    name         VARCHAR(100) CHARACTER SET UNICODE CASESPECIFIC,
    segment      CHAR(2) COMPRESS ('SM', 'MM', 'EN'),
    created      DATE FORMAT 'YYYY-MM-DD'
)
UNIQUE PRIMARY INDEX (customer_id);

COLLECT STATISTICS ON sales.orders COLUMN (customer_id);
COLLECT STATISTICS ON sales.orders COLUMN (ordered_at);
