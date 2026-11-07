CREATE SEQUENCE orders_seq START WITH 1 INCREMENT BY 1;

CREATE TABLE orders (
    order_id     NUMBER(10)    NOT NULL,
    customer_id  NUMBER(10)    NOT NULL,
    amount       NUMBER(12,2),
    discount     NUMBER,
    status       VARCHAR2(20),
    created      DATE DEFAULT SYSDATE,
    notes        CLOB
);

CREATE TABLE employees (
    employee_id  NUMBER(6) NOT NULL,
    manager_id   NUMBER(6),
    name         VARCHAR2(100),
    hired        DATE
);
