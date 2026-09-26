Writer's report (sqldesc2 arm, exchange_traded_funds_large), as returned. Drafts in `./drafts/`.

- Hardest: Q2 AADR category/fund performance empty in some years (kept years with both); Q9 no "recent price" label (low52w + lowdelta, consistent with high side); Q1 score and rank guessed; Q6 "summary of classifications" vague; Q11 top-10 plus total in one statement; Q3/Q8 623 funds without productclass left out.
- Useful: that flat columns in `funds`, `performance`, `risk_metrics` repeat their JSON documents; the joins from tickers; the rating labels in `bond_ratings`.
- Missing: nulls in `categoryperf` and `productclass`; how to get a current price. **Size: whole description ~420 KB, a question-scoped call ~87 KB -- too long; saved to a draft and searched; most answers from `./try`.** **"Likely from" hints mostly off target** (Median 1-Year Return -> `annual_returns.yearlyid`; Total Return Fund -> unrelated dividend columns).
