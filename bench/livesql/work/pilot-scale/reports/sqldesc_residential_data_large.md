Writer's report (sqldesc arm, residential_data_large), as returned.

- Dirty data throughout (case, spacing, tabs, synonyms); all comparisons normalised; variants mapped (own/owned, apt, brick house, vehicle-year forms).
- Hardest: rd_12 "Household Prosperity Score" undefined (used income bracket rank -> Apartment, 199; a dwelling/living-condition score would give 1368); rd_18 "Modern Dwelling" type unnamed (Apartment; cable kept to the three listed values); rd_19 "Municipal Piped" absent, five-way tie; rd_6 "Crowding score" undefined; rd_17 income labels vs R$ ranges.
- Useful: JSON paths (vehicle counts, newest year, income bracket, tenure, dwelling class) and the join columns. Missing: **did not say region names come in dozens of variants** (it warned for cable status and parking only); no mapping from knowledge terms to data values.
- Process: a first `information_schema` query through `./try` was blocked by the permission system; a schema dump saved to the shared scratchpad before the rule was deleted.
