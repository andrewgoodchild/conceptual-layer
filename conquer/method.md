# How to work: divide and conquer

On 100 BIRD questions, in the session it was tried, this method scored 77 where the same writer
with the same primer and no method scored 71. Re-run, it scored 64 and 62, so the size of the
gain is not established; `docs/07-what-we-measured.md` has both.

Do not write the whole query first. For each question:

1. **Split it into the smallest questions it is made of.** "Which school with the highest
   free-meal rate is in Alameda?" is three: what is the free-meal rate, which schools are in
   Alameda, which of those is highest.
2. **Answer each one on its own**, as a small query returning a few rows, and look at what
   comes back. A sub-answer that returns nothing or returns everything is a misreading, and it
   is cheaper to find here than inside the whole query.
3. **Compose the parts into one query** only once each part returns what you expect.
4. **Run the composed query** and check the rows are consistent with the parts.

The point of the method is that a wrong assumption shows up in a small query, where you can
see it, instead of in a large one, where you cannot.

Two tools make step 2 cheap:

    conquer.py model.ccm.json --db data.sqlite "LIST ..."       run it and look
    conquer.py model.ccm.json --explain "LIST ..."              what it will join, and its grain

`--explain` names the grain of the result, which is the failure the traps in the primer all
share: the query is about the right things and counts the wrong ones.
