Writer's report (sqlddlk arm, cross_border_large), as returned.

- Hardest: cb_6 no audit date (used REMED_DUE; some severities > 1 because critFindNum > FINDTALLY); cb_10 combining three definitions (ACP expansion; overdue 0-5 days; cross-border as differing JSON countries); cb_1 missing-data vs high-risk filter; output shapes chosen for cb_7, cb_2, cb_5, cb_9 (tie-breaker, 73 profiles share the top score).
- Material: sample rows helped most (metric inputs sit in jsonb columns visible only in samples); declared foreign keys made joins clear. Missing: code-to-number mappings (vendor rating A-D vs 4/3/2/1), 'Critical' sensitivity undefined, no audit date, whether "risk score" is the 0-100 JSON field or the Risk Exposure Score.
