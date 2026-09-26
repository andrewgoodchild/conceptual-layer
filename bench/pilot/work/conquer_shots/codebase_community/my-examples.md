# Worked examples in this schema (all run clean via ./try)

1. Whole-query count of a type
   THE COUNT OF User

2. Project two values off one head, ordered, limited
   LIST n, r FROM User has UserDisplayName n AND ALSO has UserReputation r ORDERED WITH r DESCENDING THE FIRST 5

3. Count with a two-hop filter (named role `has owner`)
   THE COUNT OF Post [has owner User has UserDisplayName: 'csgillespie']

4. Grouped count
   LIST u, c FROM Post p has owner User has UserId u AND ALSO THE COUNT OF p GROUPED BY u AS c ORDERED WITH c DESCENDING THE FIRST 5

5. Two filters then a hop out to a value
   LIST f FROM Comment [has User has UserId: '3025'] [has CommentCreationDate: '2014-04-23 20:29:39.0'] has Post has PostFavoriteCount f
   (dates in this DB are 'YYYY-MM-DD HH:MM:SS.0')

6. Count with function + comparison conditions, whole thing divided
   (THE COUNT OF PostLink [has PostLinkCreationDate d] [has Post has PostAnswerCount a] WHERE year(d) = 2010 AND a <= 2) / 12
   NOTE: parenthesise the aggregate. Without parens `a <= 2 / 12` binds the division into the condition.

7. Backwards walk (`is owner of`, `is of`) + distinct count
   THE DISTINCT COUNT OF u IN User [has UserLocation: 'United Kingdom'] has UserId u AND ALSO is owner of Post has PostFavoriteCount f WHERE f >= 4

8. Uncorrelated aggregate in a condition, arithmetic over two counts
   (THE COUNT OF Post [has owner User has UserReputation r] [has PostScore s] WHERE r = THE MAXIMUM User has UserReputation AND s > 50) * 100 / (THE COUNT OF Post [has owner User has UserReputation r] WHERE r = THE MAXIMUM User has UserReputation)

9. Correlated subquery filter: "users who own more than 10 posts"
   THE AVERAGE v IN User [has UserId i] [has UserUpVotes v] WHERE THE COUNT OF Post [has owner User [has UserId: !i]] > 10
   NOTE: `User: !i` is rejected (i is a value, not an instance). Use `User [has UserId: !i]`.

10. Two whole-set aggregates as two columns of ONE row
    Group by a constant computed from a bound value:
    LIST a, b FROM User [has UserId i] has UserUpVotes v AND ALSO OPTIONALLY has UserAge g AND ALSO (v - v) AS o AND ALSO THE AVERAGE v GROUPED BY o AS a AND ALSO THE AVERAGE g GROUPED BY o AS b WHERE ...
    NOTE: `THE AVERAGE v AS a` with no GROUPED BY compiles to an UNCORRELATED whole-table
    subquery that ignores the query's own WHERE -- wrong answer, repeated once per row.
    NOTE: `(1) AS o` as the group key trips a parameter-binding bug in the compiler
    ("Incorrect number of bindings"); a literal-free expression like `(v - v)` avoids it.
    NOTE: OPTIONALLY on the nullable value keeps the rows whose age is NULL, so the
    other average still covers every qualifying user.

11. Chain through an entity to reach a far type
    LIST t FROM Post has PostTitle x AND ALSO is of PostHistory has User is of Comment has CommentText t WHERE x = '...'
    NOTE: a `[...]` filter compiles to EXISTS, which here made SQLite pick a ruinous join
    order (no result in >4 min). The same restriction written as a bound name plus WHERE
    compiles to a plain predicate and returns in seconds.
