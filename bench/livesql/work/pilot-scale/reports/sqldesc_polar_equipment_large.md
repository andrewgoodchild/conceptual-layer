Writer's report (sqldesc arm, polar_equipment_large), as returned.

- Scratch: **before the rule arrived, saved a full `./schema` dump to the shared scratchpad as `schema.txt`** (a description other polar_equipment arms could in principle have read); recreated it in `./drafts/` and left the old copy.
- Hardest: Q2/Q11 knowledge.md gives two conflicting readiness definitions ("not Poor" vs "not Good"); Q20/Q5 water links only to equipment and equipment has no station -- built a map from three paths that agree where they overlap (859 of 1000 placed); Q4 grain unclear; Q19 index formula negative for almost all latencies; Q1 scores stored per equipment type, so ranks are 1; Q3 null scores first; Q10 `speed_kmh` holds "49.30 m/s" text, treated as km/h.
- **Useful: it listed exactly which values each status column holds**, gave JSON field paths and which columns link to which tables (thermal records reach equipment only through the battery link; weather through maintenance).
- Missing: no warning about the unit label/text in the speed field; no guidance on which path defines an equipment's station; that scores exist only per type; null counts (124 cycle hours, 150 wind outputs).
