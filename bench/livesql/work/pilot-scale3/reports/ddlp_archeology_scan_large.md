COMPROMISED CELL: the Docker daemon, and with it the database, went down partway through; ./try returned "Cannot connect to the Docker daemon" for about five minutes of retries. Only archeology_scan_1 was run; the other nine answers were never executed and each carries a note.

Hardest: _10 PRU (tables connect only through site and equipment); _8 PER (duplicate rows from the site join, COUNT DISTINCT); _5 DPQ (averaged per site); _9 left joins from sites; open readings in _2, _6, _4, _7.

What mattered: no foreign key from pointcloud, registration or spatial to scans -- the writer worked the (arcref, crewref) link out from row counts; mesh, processing, environment and features reach a site only through zoneref. knowledge.md's formulas were clear but "it never says which table or JSON key holds each input, or how metrics from different tables should be joined". The sample JSON rows were essential; the missing scan links were "the most important thing it failed to say".
