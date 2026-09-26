-- Legacy ERP. The MyISAM era: no foreign keys declared anywhere, naming conventions that
-- changed three times, booleans as CHAR(1), dates as strings, soft deletes, audit columns
-- on everything, and a reserved word for a table name.
-- Blaha & Premerlani (1995), "Observed idiosyncrasies of relational database designs".

CREATE TABLE CUSTOMER (
    CUSTNO      INTEGER PRIMARY KEY,
    CUST_NAME   VARCHAR(60) NOT NULL,
    ActiveFlag  CHAR(1) DEFAULT 'Y',          -- boolean as Y/N, no CHECK
    DELETED_AT  VARCHAR(19),                  -- soft delete, date as string
    created_by  VARCHAR(30),
    created_dt  VARCHAR(19),
    updated_by  VARCHAR(30),
    updated_dt  VARCHAR(19)
);
CREATE TABLE "order" (                        -- reserved word
    ORDNO       INTEGER PRIMARY KEY,
    CUSTNO      INTEGER NOT NULL,             -- FK in spirit only
    order_date  VARCHAR(19),
    STATUS_CD   CHAR(2),                      -- code with no lookup table
    created_by  VARCHAR(30),
    created_dt  VARCHAR(19)
);
CREATE TABLE ORDLIN (                         -- weak entity: parent + line number
    ORDNO       INTEGER NOT NULL,
    LINENO      INTEGER NOT NULL,
    ITEMNO      INTEGER,
    QTY         INTEGER,
    PRIMARY KEY (ORDNO, LINENO)
);
CREATE TABLE ITEM (
    ITEMNO      INTEGER PRIMARY KEY,
    DESCR       VARCHAR(80),
    UOM         CHAR(3),
    UNIT_COST   DECIMAL(11,4)
);
CREATE TABLE SHIPMENT_LOG (                   -- no primary key at all
    ORDNO       INTEGER,
    SHIPPED_DT  VARCHAR(19),
    CARRIER     VARCHAR(40)
);
