Writer's report (sqldesc arm, disaster_relief_large), as returned.

- Main problem: operations have no link to disasters; four bridge tables compared, `coordinationandevaluation` used (each disaster in at most one operation), `financials` for money questions; hubs linked via `transportation`.
- Hardest: Q3/Q8 null injury counts followed literally (599, not 955 with nulls as 0); Q6/Q7 scores across three tables; Q9 personnel in a 57-row table (missing total as 0); Q2 "all recorded disasters" kept all 1000 (312 have supplies); Q5 "ongoing" as 'Active', runway date-dependent.
- **Useful:** JSON fields; **exact value spellings ('Minimal', 'Disrupted', 'Critical')**; the caution that `costbeneusd` is stored with its unit as text. Found by sampling: `budgetallotusd`, `funds_util_pct` and the water quality index are also unit-suffixed text.
- **Missing:** which operation-disaster (or hub-disaster) link is the proper one, the many-to-many shape, and guidance on the widespread nulls.
