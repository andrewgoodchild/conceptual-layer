# How to work: say the plan before you write it

For each question, write the plan down first, in words, before any query:

1. **What is being counted, listed or measured** — one phrase.
2. **Which types the answer walks through**, in order, naming the reading of each step from
   the schema listing.
3. **Which filters apply, and to which step.** Say whether each one belongs inside a bracketed
   sub-expression (it matches without joining) or on the path (it joins and may multiply rows).
4. **What the grouping is, if there is one**, and what one row of the answer represents.

Then write the query the plan describes, run it with `./try`, and check the rows against what
the plan said one row would be. If they disagree, fix the plan first.

The plan is for you, not for the answer file. Only the query goes in `answers.json`.
