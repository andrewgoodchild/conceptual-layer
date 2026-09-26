Writer's report (sqlddlk arm, exchange_traded_funds_large), as returned. Drafts in `./drafts/` (including a full schema dump).

- Hardest: etf_6 "summary of classifications" (single drift label); etf_11 top-10 plus total; etf_3 106 funds with duration but no category left out; etf_9 recent price rebuilt as low52w + lowdelta; etf_1 premier rank and high-quality share; etf_2/4 `categoryperf` used, missing years dropped (AADR 2011-2015).
- Material: sample rows print "nan" for plain NULLs (nothing says so); JSON columns duplicate the flat ones; knowledge entries ambiguous about columns (recent price, category average, which funds count). **Declared foreign keys enough for every join.** Full schema too large to read at once (57 tables), most unneeded.
