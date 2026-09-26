Writer's report (sqldesc arm, organ_transplant_large), as returned. Drafts in `./drafts/` only.

- Hardest: ot_19 stored HLA mismatch count vs loci (used the stored count); EGS: stored `egs_val` uncorrelated with the knowledge formula (~-0.01), used the formula; urgency: bare '2'/'3' scored 1 per the definition's "any other status" rule (differs from both other arms' reading); ot_4 `blood_compat` contradicts blood types -- computed ABO from the types, size score from BMIs; smaller calls on match_ts, WIDTH_BUCKET, miles->km, ischemia, cost.
- **Helpful: cautions about numbers stored with units and mixed-case `blood_compat`; the listed value domains, including the stray '2' and '3' in `med_urgency`**; JSON paths; tables sharing the matching id as key.
- **Missing: the description silently left out `administrative_and_review.tx_cen_code` and `rec_cen_code`** -- the transplant centre Q6 needs -- found through the database's own column list via `./try`.
- Not flagged: `egs_val`/`blood_compat` disagreeing with the definitions, stored HLA counts vs values, constant `match_ts`.
