Writer's report (sqldesc2 arm, archeology_scan_large), as returned. Drafts in `./drafts/`.

- Joins: disguised names; (`arcref`, `crewref`) unique in scans, pointcloud, registration and spatial, used as the one-to-one link; mesh/processing/environment/features on `zoneref` and (`zoneref`, `equipref`).
- Hardest: scan_10 PRU chain (285 of 944 equipment null, labelled by guess); scan_8 software in 29 spellings folded into four; scan_5 DPQ computed per row then averaged; scan_2 structural state in `conservation.structstate`, found by searching, case-sensitive 'Stable' test; smaller ordering and threshold guesses.
- **Most useful:** the JSON field lists; the cautions that numbers carry units ("GB") and `flowsoft` is in mixed case; **the route caution that site-equipment routes disagree, which pushed the writer to join on (`zoneref`, `equipref`).**
- **Missed:** Structural Stability -- **the question-focused view suggested unrelated columns** and never mentioned `conservation.structstate`; how pointcloud/registration/spatial connect to scans or sites.
