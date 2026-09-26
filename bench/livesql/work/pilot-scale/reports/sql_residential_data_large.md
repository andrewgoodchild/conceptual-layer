Writer's report (sql arm, residential_data_large), as returned.

- Data cleaning in every answer: region, tenure, income bracket, dwelling class, cable status and more come in random case, stray spaces and synonyms ('Apt', 'own'/'owned', 'Y'/'have', '10-13'/'2014+'/'after 2014'); every comparison lower-cases, trims and collapses spaces.
- Hardest: rd_12 "Household Prosperity Score" undefined anywhere (used Living Condition Score); rd_17 knowledge brackets ('High Income') absent from the data, only R$ ranges; rd_18 "Modern dwelling" type unnamed; rd_19 five-way tie; "Municipal Piped" water has no matching value.
- Material: DDL sample rows showed where fields live (JSON columns `socioeconomic`, `dwelling_specs`, `vehicleinventory`; service types via `households.serviceplan`). Missing: Room_Count not named as bedrooms (zeros present); knowledge category values do not match the data; **foreign keys on `households` declared wrongly**; **three sample rows hide the corruption -- found only by profiling every column with `./try`**.
- Scratch: moved drafts into `./drafts/` after the rule and deleted its two files from the shared folder.
