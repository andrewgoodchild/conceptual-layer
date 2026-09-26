Writer's report (sqldesc arm, archeology_scan_large), as returned. Drafts in `./drafts/` (including `full.txt`, a saved full description).

- Hardest: as_5 DPQ nests eight formulas across four tables (per-site averaging chosen; 431 sites); as_10 PRU mixes processing, file size text ('24.71 GB') and mesh counts linked only by site and equipment codes; as_8 software names in 29 spellings of 17 values (grouped as stored); ambiguous shapes for as_2, as_6, as_9.
- Helped: where every JSON field lives; cautions about numbers stored with units and software names in mixed case; the three values of `conservation.structstate` (though it did not say "structural state" is that column).
- **Missed the most important thing: how scans connect to the point cloud, registration and spatial tables** -- none has a scan or site key; found by counting that (`arcref`, `crewref`) matches exactly one scan per row. Also which column holds "file size".
