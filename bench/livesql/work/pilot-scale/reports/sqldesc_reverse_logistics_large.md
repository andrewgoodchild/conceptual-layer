Writer's report (sqldesc arm, reverse_logistics_large), as returned. Scratch in `./drafts/`.

- Costs: Total Return Cost from `returns.return_details` shipping plus the `financial_management.cost_breakdown` fees; join `casetag` = `casenum` (995 of 1,500 returns); compliance via `products.product_traceability`.
- Hardest: rl_9 `logtime` in ~50 formats, bare years as 1 January (none reach the top 100) -- found by profiling; rl_5 26 site rows, no link to returns; rl_7 645 NULL risk levels kept, sorted last; column order unspecified for 17 and 2; rl_3 ratio of totals.
- **Helpful: mapped every glossary term to its exact JSON path**; showed `returns.casenum` is the key other tables point to; listed value domains ('Non-compliant', refund methods).
- Missing: no caution about the mixed date formats (mattered most); did not flag `dispcost` always 0; did not say `return_processing` has no link to returns.
- Access: full `./schema` output too large to display; reading the tool's saved copy outside the directory was refused; saved the output to `./drafts/` and searched it there.
