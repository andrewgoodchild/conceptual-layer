Writer's report (sql arm, polar_equipment_large), as returned.

- Scratch: two drafts written outside the directory before the rule (`/tmp/q2.sql`, `q3.sql` in the shared scratchpad), remade in `./drafts/`.
- Hardest: pe_10 `speed_kmh` JSON text with an "m/s" suffix, values 0-60 (used as km/h); pe_1 scores exist only per equipment type (safety rank always 1); pe_2 vs pe_11 conflicting readiness definitions in knowledge.md; pe_3 NULL LSSR sort; pe_19 filter removes nothing.
- Material: nothing says how equipment links to a station (inferred from `Communication.loc_link`, agreeing with `CabinEnvironment.loc_link`); weather reaches equipment only via `OperationMaintenance` (141 unlinked); "Registry ID" unexplained. The three sample rows exposed the traps: mislabelled unit suffixes, literal `nan`, metrics in JSON.
