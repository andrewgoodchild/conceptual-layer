All ten answers written and run; four return 0 or NULL on this data; solar_panel_15 rests on a units guess.

Hardest: _15 lifetime revenue loss (ADR taken as panel_models.degyrrate / 100); _17 mean repair cost (unavailability tops out near 4%, returns NULL; 445 snapshots predate go-live); _5 and _12 return 0 by the data; _10 filter order.

What mattered: the schema notes flagged that sites reach panel models by two routes that disagree (plant_panel_model has extra rows; the writer used plants.modhook); the notes showed which values sit inside JSON and that about 400 snapshots have no power reading; the knowledge base gave the formulas. Missing: whether ADR is a percentage or a fraction, and whether it is the spec or measured; how to turn instantaneous irradiance into the energy total. Snapshot keys upper-case, question lower-case.
