Writer's report (sqlddlk arm, polar_equipment_large), as returned. Scratch only in `drafts/build.py`.

- Hardest: pe_10 `speed_kmh` text "49.30 m/s" treated as km/h; pe_2 vs pe_11 conflicting EWR/EWRS definitions; pe_1 scores per equipment type, reliability 0-100 though documented 0-1; pe_4 grain unclear, wind NULL on 150; pe_19 all Low Resilience; pe_3 NULLs first.
- Helpful: **declared foreign keys were essential** (weather via `opmaint_link`, thermal/solar/wind via `comm_link`, stations from `Communication.loc_link`); JSON fields found. Not helpful: which route from equipment to station is intended; no warning about unit labels inside strings contradicting key names; ~25 distractor tables; 'nan' in samples, real NULLs in data.
