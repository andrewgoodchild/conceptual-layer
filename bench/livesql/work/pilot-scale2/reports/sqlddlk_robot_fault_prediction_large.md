Writer's report (sqlddlk arm, robot_fault_prediction_large), as returned. Drafts in `drafts/`.

- Links: declared foreign keys, checked on the data; the unit is the operation (1000 operations, 951 robots); maintenance 513 rows, performance 479.
- Hardest: q4 NTILE per application (blank application type on 519 operations); q10 516 operations without hours, 73 zero stops; q6 distinct robots vs rows; q3 inner join (17 vs 36), raw codes; q7/q8 model averages over one-robot series, wear rule filters almost nothing.
- Useful: sample rows (cryptic names, `joint_health` JSON keys) and declared foreign keys. Misleading: samples print 'nan' for NULLs. Not stated: rows per robot per table, which table holds current state; knowledge.md contains unrelated disaster-relief definitions. Snag: whole schema overflows output; used `information_schema` and one table at a time.
