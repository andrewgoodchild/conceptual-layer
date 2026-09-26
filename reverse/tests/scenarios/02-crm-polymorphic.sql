-- CRM with the three patterns an ORM tool cannot follow: a polymorphic association, an
-- entity-attribute-value table, and a junction table given a surrogate key so it no longer
-- looks like an association. Plus a repeating group.

CREATE TABLE contact (
    contact_id  INTEGER PRIMARY KEY,
    full_name   VARCHAR(80) NOT NULL,
    phone1      VARCHAR(24),                  -- repeating group: one fact, three columns
    phone2      VARCHAR(24),
    phone3      VARCHAR(24),
    email       VARCHAR(120) UNIQUE
);
CREATE TABLE company (
    company_id  INTEGER PRIMARY KEY,
    company_name VARCHAR(80) NOT NULL
);
CREATE TABLE note (
    note_id     INTEGER PRIMARY KEY,
    owner_type  VARCHAR(16) NOT NULL CHECK (owner_type IN ('contact','company')),
    owner_id    INTEGER NOT NULL,             -- polymorphic: no FK is possible
    body        VARCHAR(2000),
    noted_at    DATE
);
CREATE TABLE attribute_value (                -- EAV
    contact_id  INTEGER NOT NULL REFERENCES contact(contact_id),
    attr_name   VARCHAR(40) NOT NULL,
    attr_value  VARCHAR(400),
    PRIMARY KEY (contact_id, attr_name)
);
CREATE TABLE contact_company (                -- an association wearing a surrogate key
    id          INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contact(contact_id),
    company_id  INTEGER NOT NULL REFERENCES company(company_id),
    role_title  VARCHAR(60),
    UNIQUE (contact_id, company_id)
);
