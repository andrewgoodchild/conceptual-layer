-- The same conceptual model -- a Party that is either a Person or an Organisation -- rendered
-- three ways in one database, so the reverse engineer can be compared against itself.
--
--   A. table per subtype, 1:1 FK to the supertype  (the shape rule 7 is written for)
--   B. single table, discriminator plus nullable column groups  (the shape rule 8 detects)
--   C. table per concrete class, no supertype table at all  (nothing to detect)

-- A ---------------------------------------------------------------------------
CREATE TABLE a_party (
    party_id    INTEGER PRIMARY KEY,
    party_name  VARCHAR(80) NOT NULL
);
CREATE TABLE a_person (
    party_id    INTEGER PRIMARY KEY REFERENCES a_party(party_id),
    birth_date  DATE,
    given_name  VARCHAR(40)
);
CREATE TABLE a_organisation (
    party_id    INTEGER PRIMARY KEY REFERENCES a_party(party_id),
    abn         VARCHAR(11),
    founded     DATE
);

-- B ---------------------------------------------------------------------------
CREATE TABLE b_party (
    party_id    INTEGER PRIMARY KEY,
    party_name  VARCHAR(80) NOT NULL,
    party_kind  VARCHAR(12) NOT NULL CHECK (party_kind IN ('person','organisation')),
    birth_date  DATE,
    given_name  VARCHAR(40),
    abn         VARCHAR(11),
    founded     DATE
);

-- C ---------------------------------------------------------------------------
CREATE TABLE c_person (
    person_id   INTEGER PRIMARY KEY,
    person_name VARCHAR(80) NOT NULL,
    birth_date  DATE,
    given_name  VARCHAR(40)
);
CREATE TABLE c_organisation (
    org_id      INTEGER PRIMARY KEY,
    org_name    VARCHAR(80) NOT NULL,
    abn         VARCHAR(11),
    founded     DATE
);
