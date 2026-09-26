-- The same order/line model keyed two ways. The conceptual model is identical; only the
-- identification scheme differs, so the two halves should differ ONLY in reference mode and
-- in where the uniqueness constraints land.
--
--   N. natural composite keys
--   S. surrogate keys with the natural key kept as a UNIQUE constraint

-- N ---------------------------------------------------------------------------
CREATE TABLE n_customer (
    cust_code   VARCHAR(10) PRIMARY KEY,
    cust_name   VARCHAR(60) NOT NULL
);
CREATE TABLE n_order (
    cust_code   VARCHAR(10) NOT NULL REFERENCES n_customer(cust_code),
    order_seq   INTEGER NOT NULL,
    order_date  DATE NOT NULL,
    PRIMARY KEY (cust_code, order_seq)
);
CREATE TABLE n_order_line (
    cust_code   VARCHAR(10) NOT NULL,
    order_seq   INTEGER NOT NULL,
    line_no     INTEGER NOT NULL,
    qty         INTEGER NOT NULL,
    PRIMARY KEY (cust_code, order_seq, line_no),
    FOREIGN KEY (cust_code, order_seq) REFERENCES n_order(cust_code, order_seq)  -- composite FK
);

-- S ---------------------------------------------------------------------------
CREATE TABLE s_customer (
    customer_id INTEGER PRIMARY KEY,
    cust_code   VARCHAR(10) NOT NULL UNIQUE,
    cust_name   VARCHAR(60) NOT NULL
);
CREATE TABLE s_order (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES s_customer(customer_id),
    order_seq   INTEGER NOT NULL,
    order_date  DATE NOT NULL,
    UNIQUE (customer_id, order_seq)
);
CREATE TABLE s_order_line (
    order_line_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES s_order(order_id),
    line_no       INTEGER NOT NULL,
    qty           INTEGER NOT NULL,
    UNIQUE (order_id, line_no)
);
