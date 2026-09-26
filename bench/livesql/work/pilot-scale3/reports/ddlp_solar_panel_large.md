All ten answers written and run; q17, q5 and q12 return empty or zero, each with a note.

Hardest: _17 (unavailability tops out near 4%, NULL); _5 (0 under every reading); _12 (soiling tops out at 14.99%); _15 lifetime revenue loss (ADR computed per snapshot from cumulative_deg_pct over positive plant age; about 1.894e10; heavy judgement); _10 filter order.

What mattered: the measurements sit in nested JSON (elec_perf_snapshot, mech_health_snapshot) and ./schema showed only truncated sample rows, so the writer printed a full snapshot to find the key names; plants reach panel models two ways and 61 disagree (used plants.modhook); NaN in number columns; MTBF has 400 missing. The knowledge base gave the formulas, but not how to take plant age when a snapshot predates go-live, nor whether Performance Ratio and availability are stored or computed.
