Writer's report (sqlddlk arm, organ_transplant_large), as returned.

- Scratch: wrote one helper (`gen.py`) to the shared scratchpad before the rule arrived, then moved it into `./drafts/`. A no-argument `./schema` saved its output outside the directory; reading it was denied, so never seen.
- Hardest: ot_19 stored `hla_mis_count` contradicts the raw HLA values; ot_13/ot_8 EGS computed vs stored `egs_val`, WIDTH_BUCKET sixth bucket left as is; ot_17/ot_8 ischemia components unnamed, distances in miles converted; ot_7/ot_2 bare urgency codes; ot_4 `blood_compat` contradicts the blood types (used the column).
- Material: DDL foreign keys; sample rows exposed unit-suffixed text, JSON fields and random-case `blood_compat`. Missing: cold/warm ischemia columns, stored vs computed scores, bare urgency mapping, constant `match_ts`; ~40 unrelated noise tables mixed in.
