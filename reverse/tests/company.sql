-- A test schema chosen to exercise every rule, including the ones that should fail.
CREATE TABLE department (
    dept_code   VARCHAR(8)  PRIMARY KEY,                       -- rule 1: simple PK
    dept_name   VARCHAR(64) NOT NULL UNIQUE,                   -- rules 2, 5
    budget      DECIMAL(12,2)
);
CREATE TABLE employee (
    emp_nr      INTEGER PRIMARY KEY,
    emp_name    VARCHAR(64) NOT NULL,
    salary      DECIMAL(10,2),
    gender      CHAR(1) CHECK (gender IN ('M','F','X')),       -- rule 6
    hired       DATE NOT NULL,
    dept_code   VARCHAR(8) NOT NULL REFERENCES department(dept_code),   -- rule 3
    manager_nr  INTEGER REFERENCES employee(emp_nr)            -- rule 3, self-reference
);
CREATE TABLE manager (                                          -- rule 7: subtype candidate
    emp_nr      INTEGER PRIMARY KEY REFERENCES employee(emp_nr),
    car_space   VARCHAR(8)
);
CREATE TABLE project (
    proj_code   VARCHAR(8) PRIMARY KEY,
    proj_name   VARCHAR(64) NOT NULL,
    priority    INTEGER CHECK (priority BETWEEN 1 AND 5)        -- rule 6, range
);
CREATE TABLE assignment (                                       -- rule 4: association, objectified
    emp_nr      INTEGER NOT NULL REFERENCES employee(emp_nr),
    proj_code   VARCHAR(8) NOT NULL REFERENCES project(proj_code),
    hours       INTEGER NOT NULL,
    PRIMARY KEY (emp_nr, proj_code)
);
CREATE TABLE audit_log (                                        -- blocker: no primary key
    at          TIMESTAMP,
    note        VARCHAR(200)
);
CREATE TABLE party (                                            -- rule 8: discriminator shape
    party_id    INTEGER PRIMARY KEY,
    party_type  VARCHAR(10) NOT NULL CHECK (party_type IN ('person','company')),
    given_name  VARCHAR(64),
    family_name VARCHAR(64),
    trading_as  VARCHAR(64),
    abn         VARCHAR(11)
);
CREATE VIEW busy_employee AS
    SELECT emp_nr, COUNT(*) AS n FROM assignment GROUP BY emp_nr;

INSERT INTO department VALUES ('SALES','Sales',900000),('ENG','Engineering',2400000),('HR','People',300000);
INSERT INTO employee VALUES
  (1,'Ada Lovelace',185000,'F','2019-03-01','ENG',NULL),
  (2,'Alan Turing',172000,'M','2020-07-15','ENG',1),
  (3,'Grace Hopper',164000,'F','2018-01-09','ENG',1),
  (4,'Jean Bartik',98000,'F','2021-11-02','SALES',NULL),
  (5,'Kay Antonelli',101500,'F','2022-05-30','SALES',4),
  (6,'Betty Holberton',88000,'X','2023-02-14','HR',NULL);
INSERT INTO manager VALUES (1,'A-12'),(4,'B-03');
INSERT INTO project VALUES ('APOLLO','Apollo',1),('MERC','Mercury',3),('GEM','Gemini',5);
INSERT INTO assignment VALUES
  (1,'APOLLO',120),(1,'MERC',40),(2,'APOLLO',80),(3,'APOLLO',60),(3,'GEM',100),
  (4,'MERC',30),(5,'MERC',55);
INSERT INTO party VALUES
  (1,'person','Ada','Lovelace',NULL,NULL),(2,'company',NULL,NULL,'Analytical Engines','12345678901');
