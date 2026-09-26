Writer's report (sqlddlk arm, cybermarket_pattern_large), as returned.

- Hardest: pattern_2/9 Session Anonymity labels do not exist in the data (`AnonLevel` is text 1-10; bucketed 7+/4+/rest); pattern_2 buckets with no cut-offs (NTILE(3)); pattern_3 formula needs an `average_price` no column holds, used the stored `liq_rate`; pattern_7 thresholds unspecified; pattern_4/6 "metrics related to" unspecified.
- Material: declared foreign keys covered the joins that mattered; sample rows showed values live inside JSON fields; numbers stored as text with units. Missing: links from knowledge labels to columns; RepScore blank for 387 of 954 markets; no cut-offs. **The full `./schema` dump was too large (175 KB) to read, so the writer read column lists from `information_schema` through `./try`.**
