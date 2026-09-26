-- Patterns that break the "one foreign key, one fact type" assumption.
--   two foreign keys from one table to the SAME table (origin / destination)
--   a composite foreign key
--   a self-referencing hierarchy
--   a ternary association (crew member, flight, role)
--   a lookup/code table -- the shape that should probably not be an entity type but always is
--   a 1:1 pair that is vertical partitioning, not subtyping: the trap rule 7 falls into

CREATE TABLE region (
    region_code VARCHAR(8) PRIMARY KEY,
    region_name VARCHAR(60) NOT NULL,
    parent_code VARCHAR(8) REFERENCES region(region_code)      -- self-reference
);
CREATE TABLE airport (
    iata        CHAR(3) PRIMARY KEY,
    airport_name VARCHAR(80) NOT NULL,
    region_code VARCHAR(8) REFERENCES region(region_code)
);
CREATE TABLE aircraft_type (
    type_code   VARCHAR(8) PRIMARY KEY,
    seats       INTEGER NOT NULL
);
CREATE TABLE flight (
    airline     CHAR(2) NOT NULL,
    flight_no   INTEGER NOT NULL,
    origin      CHAR(3) NOT NULL REFERENCES airport(iata),      -- same target...
    destination CHAR(3) NOT NULL REFERENCES airport(iata),      -- ...twice
    type_code   VARCHAR(8) REFERENCES aircraft_type(type_code),
    PRIMARY KEY (airline, flight_no)
);
CREATE TABLE flight_extra (                    -- vertical partition, NOT a subtype
    airline     CHAR(2) NOT NULL,
    flight_no   INTEGER NOT NULL,
    meal_service CHAR(1),
    notes       VARCHAR(400),
    PRIMARY KEY (airline, flight_no),
    FOREIGN KEY (airline, flight_no) REFERENCES flight(airline, flight_no)
);
CREATE TABLE crew (
    crew_id     INTEGER PRIMARY KEY,
    crew_name   VARCHAR(60) NOT NULL
);
CREATE TABLE crew_role (                       -- lookup table: code + description
    role_code   CHAR(4) PRIMARY KEY,
    role_desc   VARCHAR(40) NOT NULL
);
CREATE TABLE flight_crew (                     -- ternary association
    airline     CHAR(2) NOT NULL,
    flight_no   INTEGER NOT NULL,
    crew_id     INTEGER NOT NULL REFERENCES crew(crew_id),
    role_code   CHAR(4) NOT NULL REFERENCES crew_role(role_code),
    PRIMARY KEY (airline, flight_no, crew_id, role_code),
    FOREIGN KEY (airline, flight_no) REFERENCES flight(airline, flight_no)
);
