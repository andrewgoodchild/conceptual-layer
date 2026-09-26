# Reference judge

You are judging *candidate foreign-key references* that a statistical pass proposed for one
database whose schema declares no references. You will be given one file:

    bench/ablation/work/llm/<database>.candidates.json

Read that file and nothing else. Do not open the database, the repository, the model files,
or any other file: the point of the exercise is what a reader can tell from the evidence in
the file alone. Do not search the web.

Each candidate says: a source table and column, a target table and its key column, how many
rows and distinct values the source has, how many rows the target has, a score (0-6, how far
the statistical signals agree) and the signals themselves, and five sample values from each
side. Every candidate's source values are contained in the target key's values -- that is
how it got proposed -- so containment alone is not evidence; the question is whether the
reference is *meant*: whether this column is how rows of the source point at rows of the
target, as a database designer would have declared it.

Judge each candidate on the whole picture: what the names say (a column called
`hospital_ref` in a table of equipment pointing at a table of hospitals), whether the sample
values look like identifiers of that target rather than coincidental overlap of small
integers or codes, whether the cardinalities make sense (a lookup table of four rows
referenced by thousands is ordinary; two unrelated surrogate sequences nesting because one is
shorter is the classic false positive), and whether a designer would plausibly have wanted
this relationship. A column that is the source table's own primary key and is contained in
another table's key is the one-to-one shape -- an entity split across tables sharing its id --
and can be a real reference.

Write your verdicts to

    bench/ablation/work/llm/<database>.verdicts.json

as JSON of this shape, one entry per candidate, using the candidate's `id` verbatim:

    {"database": "<database>",
     "verdicts": [{"id": "<id>", "verdict": "yes" | "no" | "unsure", "reason": "<one line>"}]}

Be decisive: "unsure" is for a genuine coin-flip, not for caution. Say "yes" when the
evidence reads as a real reference and "no" when it reads as coincidence. When you are done,
reply with one line: how many yes, no and unsure.
