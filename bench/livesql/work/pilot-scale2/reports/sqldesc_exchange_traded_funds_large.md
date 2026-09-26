Writer's report (sqldesc arm, exchange_traded_funds_large), as returned.

- Hardest: Q9 "recent price" not stored (low52w + lowdelta = high52w + highdelta); Q1 high-quality credit from `bond_allocations` x `bond_ratings`, "premier rank" undefined; Q6 vague summary; Q11 top-10 plus total; Q2/Q4 missing returns left out; Q8 counts funds with both metrics; Q3 funds with a duration; Q5 formula as written.
- Most useful: that other tables refer to a fund by its ticker (`annual_returns.portfolioref`, `risk_metrics.investmentref`, `performance.productref`, `bond_allocations.fundlink`) rather than its declared key; that `funds.productclass` names a category; what is inside each JSON column.
- Not covered: the recent-price formula; the rating spellings (found by querying `bond_ratings`); whether missing returns count.
- Tooling: full `./schema` too large and saved outside the directory (not allowed to open); one redirect into `./drafts` refused; worked with narrower words and inline filtering.
