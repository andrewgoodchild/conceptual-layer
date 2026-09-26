Writer's report (sqlddlk arm, reverse_logistics_large), as returned. Scratch only in `drafts/gen.py`.

- Where the data lives: shipping fee/fraud/risk in `returns.return_details`; other fees, recovery, carbon, disposal and refund methods in `financial_management.cost_breakdown` (995 of 1,500 returns have a financial row); regulatory compliance in `products.product_traceability`.
- Hardest: rl_9 `logtime` free text in ~50 formats, 254 year-only (treated as 1 January); rl_7 645 returns without a risk level (NULL, sorted last); rl_3 ratio of sums; rl_5 one row per site, no link to returns; rl_17 net impact per refund method.
- Material: DDL shows facts are JSON keys but not which terms sit where (found via `./try`); `dispcost` always 0; **compliance status only findable by searching the column catalogue with `./try` -- `./schema` with those words returned 27 of 47 tables**; channel list mismatch ('Collection Point').
- Process: read the full `./schema` dump from a file saved outside the directory once early on (only `./schema` output); a later search of it was blocked.
