Writer's report (sqldesc arm, labor_certification_applications_large), as returned. Drafts in `drafts/`.

- **Got almost nothing usable from `./schema`**: its output was 100-276 KB, too large to show; saving it into the working folder to search was refused by the permission system ("PII Data Handling"). Worked out the structure from `information_schema` and row profiling via `./try`. **This cell is close to a no-description arm.**
- Data: every case certified (status in three spellings); dates in three text formats; 216 blank decision dates.
- Hardest: Q16 all jurisdictions at 100% (tie-break by cases); Q14 no workforce data; Q13 no population data, shape ambiguous; Q15 vague categories; Q11 calendar-month buckets; Q8 wage strings cast.
- Links found by itself: case -> attorney via `case_attorney` (`preplink` is the preparer's email); case -> employer via `homefirm`/`homezip`; NAICS in employer contact-info JSON; wages via worksite `wagetrack` -> `prevailing_wage`.
