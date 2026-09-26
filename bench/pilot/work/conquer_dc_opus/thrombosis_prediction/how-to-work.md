# How to work: divide and conquer

Do not write the whole query first. For each question:

1. **Split it into the smallest questions it is made of.** "Which school with the highest
   free-meal rate is in Alameda?" is three: what is the free-meal rate, which schools are in
   Alameda, which of those is highest.
2. **Answer each one on its own** with `./try`, as a small query returning a few rows. Look at
   what comes back. A sub-answer that returns nothing or returns everything is a misreading,
   and it is cheaper to find here than in the whole query.
3. **Compose the parts into one query** only once each part returns what you expect.
4. Run the composed query and check the rows are consistent with the parts.

The point of the method is that a wrong assumption shows up in a small query, where you can
see it, instead of in a large one, where you cannot.
