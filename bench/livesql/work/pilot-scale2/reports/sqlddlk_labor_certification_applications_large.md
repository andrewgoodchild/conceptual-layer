Writer's report (sqlddlk arm, labor_certification_applications_large), as returned. Draft in `./drafts/gen.py`.

- Data: every case is certified (981), so approval rates cannot tell right from wrong; status spelled three ways; ties decide some orderings (Q16, Q1, Q3).
- Hardest: Q11 filing-window gap unmeasured, two date text formats (YYYY/MM/DD and D/MM/YYYY); Q13 "adjusted for population" with no population data, result shape ambiguous; Q15 Generalist/Hybrid undefined; Q14 "total workforce" absent.
- Material: 49 tables, ~7 matter; declared foreign keys essential (wages reach a case only via `case_worksite.wagetrack` -> `prevailing_wage.trackno`); facts inside JSON (wages as text "$130000.00", "USD 116,979.00"; NAICS in `employer_contact_info`).
- Access: the permission system blocked reading the saved full `./schema` output and a `./schema` call on worksite/wage tables ("personal-data handling"); worked from `information_schema`, `pg_constraint`, `pg_enum`.
