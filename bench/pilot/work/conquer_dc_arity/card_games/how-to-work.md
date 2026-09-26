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

## Before you record an answer, count what the question asked for

Read the question again and count the separate things it asks you to return. "List the
iodine and sulfur counts" asks for two. "Give the driver's name, team and points" asks for
three. "For each category, give the type" asks for two, because the category is one of the
things to return and not only a grouping. Then count the names after `LIST` in your query.
If the two counts differ, the answer is wrong however well it runs -- a query that returns
one column where the question asked for two cannot be right, and nothing in `./try` will
tell you, because one column of correct numbers looks exactly like a correct answer.

Fix the count before you record the answer.
