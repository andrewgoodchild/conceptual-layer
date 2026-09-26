Writer's report (sql arm, reverse_logistics_large), as returned. Drafts in `drafts/`.

- Hardest: rl_9 `returns.logtime` free text in six formats, 254 year-only rows sorted last; rl_5 `return_processing` one row per site with no key to `returns` (degenerate APT); rl_7 645 of 1,500 returns lack a fraud level (weighted 0); rl_3 "portfolio-wide average" read as a ratio of totals.
- Material: sample rows showed the JSON paths for costs (`returns.return_details`, `financial_management.cost_breakdown`, `products.product_traceability`). Traps: plain `dispcost` is 0 in every row (JSON disposal cost used); `policycomp` 'Non-compliant' is policy, not product, compliance; knowledge.md channels do not match the data ('Collection Point'); only 995 of 1,500 returns have a financial row.
