-- One multi-valued fact -- a person has phone numbers -- modelled three ways. Only the first
-- is recoverable as a multi-valued fact type; the tool should say so about the other two
-- rather than quietly producing three unrelated single-valued facts, or one string.

-- A. a separate table: the normalised form
CREATE TABLE a_person (
    person_id   INTEGER PRIMARY KEY,
    person_name VARCHAR(60) NOT NULL
);
CREATE TABLE a_person_phone (
    person_id   INTEGER NOT NULL REFERENCES a_person(person_id),
    phone_seq   INTEGER NOT NULL,
    phone_no    VARCHAR(24) NOT NULL,
    PRIMARY KEY (person_id, phone_seq)
);

-- B. repeating columns
CREATE TABLE b_person (
    person_id   INTEGER PRIMARY KEY,
    person_name VARCHAR(60) NOT NULL,
    phone_1     VARCHAR(24),
    phone_2     VARCHAR(24),
    phone_3     VARCHAR(24)
);

-- C. one delimited string
CREATE TABLE c_person (
    person_id   INTEGER PRIMARY KEY,
    person_name VARCHAR(60) NOT NULL,
    phones      VARCHAR(200)          -- 'x,y,z'
);
