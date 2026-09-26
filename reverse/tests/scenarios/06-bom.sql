-- Bill of materials. A recursive many-to-many -- a part contains parts -- which is the shape
-- that makes a ring constraint and, in ORM, two roles played by the same object type.
-- Also: an association whose own key is a surrogate, and a table whose only key is a FK pair
-- plus a date, which is a common way to version a relationship.

CREATE TABLE part (
    part_no     VARCHAR(20) PRIMARY KEY,
    part_desc   VARCHAR(80) NOT NULL,
    is_assembly CHAR(1) NOT NULL DEFAULT 'N' CHECK (is_assembly IN ('Y','N'))
);
CREATE TABLE bom (                             -- part contains part, with a quantity
    parent_no   VARCHAR(20) NOT NULL REFERENCES part(part_no),
    child_no    VARCHAR(20) NOT NULL REFERENCES part(part_no),
    qty_per     DECIMAL(9,3) NOT NULL,
    PRIMARY KEY (parent_no, child_no)
);
CREATE TABLE supplier (
    supplier_id INTEGER PRIMARY KEY,
    supplier_nm VARCHAR(60) NOT NULL
);
CREATE TABLE part_price (                      -- versioned relationship: key includes a date
    part_no     VARCHAR(20) NOT NULL REFERENCES part(part_no),
    supplier_id INTEGER NOT NULL REFERENCES supplier(supplier_id),
    effective   DATE NOT NULL,
    price       DECIMAL(11,4) NOT NULL,
    PRIMARY KEY (part_no, supplier_id, effective)
);
