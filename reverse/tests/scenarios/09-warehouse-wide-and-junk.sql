-- Shapes a data warehouse throws at a conceptual modeller, none of which had ever been tried.
--
--   * a star fact table: several foreign keys, measures, no primary key, plus a degenerate
--     dimension (order_number, a key with no dimension table behind it)
--   * a junk dimension: Kimball's bundle of low-cardinality flags behind a surrogate key, so
--     the fact carries one key instead of five. A storage device, not a business concept.
--   * a wide denormalised dimension, here 40 columns of the same stem -- enough to show what
--     hundreds do without making the fixture unreadable
--   * a role-playing dimension (date_dim, referenced once here but twice in real schemas)

CREATE TABLE date_dim (date_key INTEGER PRIMARY KEY, full_date TEXT, year INTEGER,
                       quarter INTEGER, month INTEGER, day_of_week TEXT, is_weekend TEXT);

CREATE TABLE product_dim (product_key INTEGER PRIMARY KEY, name TEXT, category TEXT);

-- The junk dimension. Every non-key column is a flag or a short code.
CREATE TABLE order_junk_dim (junk_key INTEGER PRIMARY KEY, is_gift TEXT, is_rush TEXT,
                             payment_type TEXT, channel TEXT, is_return TEXT);

-- The wide one: a repeating group spread across columns, which rule 2b should name.
CREATE TABLE customer_dim (customer_key INTEGER PRIMARY KEY,
  attr_01 TEXT, attr_02 TEXT, attr_03 TEXT, attr_04 TEXT, attr_05 TEXT, attr_06 TEXT,
  attr_07 TEXT, attr_08 TEXT, attr_09 TEXT, attr_10 TEXT, attr_11 TEXT, attr_12 TEXT,
  attr_13 TEXT, attr_14 TEXT, attr_15 TEXT, attr_16 TEXT, attr_17 TEXT, attr_18 TEXT,
  attr_19 TEXT, attr_20 TEXT, attr_21 TEXT, attr_22 TEXT, attr_23 TEXT, attr_24 TEXT,
  attr_25 TEXT, attr_26 TEXT, attr_27 TEXT, attr_28 TEXT, attr_29 TEXT, attr_30 TEXT,
  attr_31 TEXT, attr_32 TEXT, attr_33 TEXT, attr_34 TEXT, attr_35 TEXT, attr_36 TEXT,
  attr_37 TEXT, attr_38 TEXT, attr_39 TEXT, attr_40 TEXT);

-- The fact table. No primary key, which used to be fatal; rule 1b reads it as an
-- association over its foreign keys, objectified by the measures.
CREATE TABLE sales_fact (
  date_key INTEGER, customer_key INTEGER, junk_key INTEGER, product_key INTEGER,
  order_number TEXT, quantity INTEGER, amount REAL,
  FOREIGN KEY (date_key) REFERENCES date_dim(date_key),
  FOREIGN KEY (customer_key) REFERENCES customer_dim(customer_key),
  FOREIGN KEY (junk_key) REFERENCES order_junk_dim(junk_key),
  FOREIGN KEY (product_key) REFERENCES product_dim(product_key));
