Writer's report (sqldesc arm, robot_fault_prediction_large), as returned. Drafts in `./drafts/`.

- Hardest: Q4 NTILE per application, robot id column added; Q6 rows vs distinct robots (counted rows); Q3 only 'Assembly' exists, raw codes; Q10 zero-stop division; Q1/Q7 urgency threshold, unstated order; Q11 tie at the cut.
- Useful: where key columns live (`robot_details`, not `robot_record`); maintenance and performance tables are subtypes of the actuation record; JSON paths per joint; application-type values.
- Missing: several operations per robot (1000 for 951), found by counting; nothing on rows per robot, zero stop counts, or data types (from `information_schema`). Too big: ~210 KB, still hard to read when narrowed.
