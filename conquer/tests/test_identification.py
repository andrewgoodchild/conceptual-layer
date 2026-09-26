#!/usr/bin/env python3
"""What names an instance, end to end: from the rows to the line a query author reads.

LiveSQLBench's SQLite tier lost nine answers whose every figure was right. Each asked for a
thing's id, each type had more than one id-shaped value, and the schema listing -- the one
surface a writer reads -- never said which of them identifies the type. The fixture below is
the three shapes that did it, cut down:

    credit     one instance spread over a chain of 1:1 tables. The identity is spelled three
               ways (`coreregistry`, `emplcoreref`, `expemplref`), and beside it sits
               `clientref`, a second code nothing references. Asked for customer ids, the
               writer took the one named for clients.
    cross_db   `flowtag` sounds like the flow's id and is not even unique.
    crypto     `orders` is keyed by a row number nothing mentions, and referenced everywhere
               by `recordvault`.

Two things are pinned. That the listing says what the model already knew -- nothing here
needed a new kind of fact, only to be shown. And that rule 1d, which does change the model,
fires on crypto's shape alone and leaves every fact a query can read exactly as it was.

    test_identification.py [-v] [--only SUBSTRING]
"""

import argparse
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "reverse"))

import catalog as catalog_mod      # noqa: E402
import conquer as driver           # noqa: E402
import derive as derive_mod        # noqa: E402
import population as pop           # noqa: E402

DDL = """
CREATE TABLE core (coreregistry TEXT PRIMARY KEY, clientref TEXT NOT NULL, seg TEXT);
CREATE TABLE income (emplcoreref TEXT PRIMARY KEY REFERENCES core(coreregistry),
                     mthincome REAL);
CREATE TABLE assets (expemplref TEXT PRIMARY KEY REFERENCES income(emplcoreref),
                     totassets REAL);
CREATE TABLE flow (recordregistry TEXT PRIMARY KEY, flowtag TEXT NOT NULL, mb REAL);
CREATE TABLE risk (risktrace INTEGER PRIMARY KEY,
                   flowlink TEXT REFERENCES flow(recordregistry), score REAL);
CREATE TABLE orders (orderspivot INTEGER PRIMARY KEY, recordvault TEXT NOT NULL, qty INTEGER);
CREATE TABLE fee (feeid INTEGER PRIMARY KEY, orderslink TEXT REFERENCES orders(recordvault),
                  amt REAL);
CREATE TABLE margin (mid INTEGER PRIMARY KEY, ordervault TEXT REFERENCES orders(recordvault),
                     held REAL);
-- a foreign key onto a column that repeats: declared, and refuted by its own rows
CREATE TABLE batch (batchpivot INTEGER PRIMARY KEY, lot TEXT NOT NULL);
CREATE TABLE sample (sid INTEGER PRIMARY KEY, lotref TEXT REFERENCES batch(lot));
-- a key of two columns is one spelling of the identity, not two
CREATE TABLE lab (pid INTEGER, day TEXT, v REAL, PRIMARY KEY (pid, day));
-- referenced by one column that is sometimes absent: no instance can be named by it
CREATE TABLE depot (depotpivot INTEGER PRIMARY KEY, code TEXT);
CREATE TABLE truck (tid INTEGER PRIMARY KEY, depotcode TEXT REFERENCES depot(code));
"""
ROWS = 60           # past population.MIN_ROWS, or nothing found in the data is evidence


def build(path):
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    for i in range(ROWS):
        conn.execute("INSERT INTO core VALUES (?,?,?)",
                     ("CS%04d" % i, "CU%04d" % (9000 - i), "AB"[i % 2]))
        conn.execute("INSERT INTO income VALUES (?,?)", ("CS%04d" % i, 1000.0 + i))
        conn.execute("INSERT INTO assets VALUES (?,?)", ("CS%04d" % i, 5000.0 * i))
        # two flows to a tag: the id-sounding column that identifies nothing
        conn.execute("INSERT INTO flow VALUES (?,?,?)",
                     ("CB%04d" % i, "DF%04d" % (i // 2), i * 1.5))
        conn.execute("INSERT INTO risk VALUES (?,?,?)", (i, "CB%04d" % i, i / 10.0))
        # the vault code runs against the row number, so reading one for the other is a
        # different answer on every row rather than the same one by luck
        conn.execute("INSERT INTO orders VALUES (?,?,?)", (i + 1, "OB%04d" % (500 - i), i))
        conn.execute("INSERT INTO fee VALUES (?,?,?)", (i, "OB%04d" % (500 - i), 0.5))
        conn.execute("INSERT INTO margin VALUES (?,?,?)", (i, "OB%04d" % (500 - i % 7), 2.0))
        conn.execute("INSERT INTO batch VALUES (?,?)", (i, "L%d" % (i % 9)))
        conn.execute("INSERT INTO sample VALUES (?,?)", (i, "L%d" % (i % 9)))
        conn.execute("INSERT INTO lab VALUES (?,?,?)", (i % 6, "2026-01-%02d" % (i + 1), 1.0))
        conn.execute("INSERT INTO depot VALUES (?,?)", (i, None if i == 7 else "D%03d" % i))
        conn.execute("INSERT INTO truck VALUES (?,?)", (i, "D%03d" % (i % 5)))
    conn.commit()
    return conn


def derive(conn, path, prefer=False):
    """The model as `reverse.py --infer-partitions --infer-identifiers` builds it, and with
    `--prefer-referenced-keys` when asked. Returns `(model, what rule 1d applied)`."""
    cat = catalog_mod.from_sqlite(path)
    applied = pop.prefer_referenced_keys(conn, cat) if prefer else []
    analysis = pop.analyse(conn, cat)
    absorb = {c: p for c, p, _, _, covers in pop.partitions(conn, cat) if covers}
    model, report = derive_mod.derive(cat, absorb=absorb)
    pop.apply_alternate_keys(analysis, model, report)
    return model, applied


def rows(model, conn, query):
    _, statement, params = driver.transpile(model, query)
    return sorted(conn.execute(statement, params).fetchall())


def cases(conn, path):
    model, _ = derive(conn, path)
    named = driver.identification(model)
    concept = {c["name"]: c for c in model["concepts"]}
    core, flow, order = named["et.Core"], named["et.Flow"], named["et.Order"]

    # -- credit: one identity, several spellings, and a second identifier beside it ---------
    yield ("the identifier is the value the key holds",
           core["by"] == ["CoreRegistry"], "Core by %s" % core["by"])
    yield ("an absorbed partition's key is the same identity under another name",
           sorted(core["stored"]) == ["assets.expemplref", "core.coreregistry",
                                      "income.emplcoreref"],
           "stored as %s" % core["stored"])
    yield ("and the entity's own table is named first",
           core["stored"][:1] == ["core.coreregistry"], "first is %s" % core["stored"][:1])
    terms = set(concept["CoreRegistry"].get("terms", []))
    yield ("the partition keys become vocabulary for the identifier, so a question or a "
           "definition that says `expemplref` matches it",
           {"emplcoreref", "expemplref"} <= terms, "terms %s" % sorted(terms))
    yield ("but not names: nothing new resolves in a query",
           "CoreExpemplref" not in concept and "CoreEmplcoreref" not in concept,
           "no value type minted for a partition key")
    yield ("a never-repeating code beside the key is a second identifier",
           ("CoreClientref", [], True) in core["also"], "also %s" % core["also"])

    # -- cross_db: the id-sounding column that identifies nothing ---------------------------
    yield ("what other tables hold is listed beside the identifier",
           flow["by"] == ["FlowRecordregistry"] and flow["referenced"] == ["risk.flowlink"],
           "Flow by %s, referenced %s" % (flow["by"], flow["referenced"]))
    yield ("a tag that repeats is not offered as an identifier, whatever it is called",
           flow["also"] == [], "also %s" % flow["also"])

    # -- crypto: the key nothing references, before rule 1d ---------------------------------
    yield ("a referenced column beside an unreferenced key is shown with who holds it",
           order["by"] == ["OrderSpivot"] and
           [(n, r) for n, r, _ in order["also"]] ==
           [("OrderRecordvault", ["fee.orderslink", "margin.ordervault"])],
           "Order by %s, also %s" % (order["by"], order["also"]))
    batch = named["et.Batch"]
    yield ("a referenced column that repeats is reported as referenced, never as unique",
           batch["also"] == [("BatchLot", ["sample.lotref"], False)], "also %s" % batch["also"])

    lab = named["et.Lab"]
    yield ("a composite key is one spelling of the identity, not one per column",
           lab["by"] == ["LabPid", "LabDay"] and lab["stored"] == ["lab.(pid, day)"],
           "Lab by %s, stored %s" % (lab["by"], lab["stored"]))

    # -- the listing a writer reads ---------------------------------------------------------
    text = driver.describe(model)
    section = text.split("Identification", 1)[-1].split("Predicate readings", 1)[0]
    yield ("the listing has an identification section, above the readings",
           "Identification" in text and
           text.index("Identification") < text.index("Predicate readings"),
           "section %s" % ("present" if "Identification" in text else "MISSING"))
    yield ("it says the identity is one value stored several ways",
           "one value, stored as core.coreregistry" in section and "expemplref" in section,
           "Core's lines")
    yield ("it names the second identifier and says nothing refers to an instance by it",
           "also unique: CoreClientref" in section
           and "nothing refers to a Core by it" in section, "Core's lines")
    yield ("where nothing refers to the key, it leads with the value the schema uses",
           "Order                        OrderRecordvault -- what the rest of the schema "
           "names an Order by: fee.orderslink, margin.ordervault hold it. Asked for its id, "
           "list this." in section
           and "OrderSpivot is the declared key, and nothing refers to an Order by it"
           in section, "Order's lines")
    yield ("and a type stored under one key is not said to be stored several ways",
           "stored as lab." not in section, "Lab's line is its identifier alone")
    narrowed = driver.describe(model, "the total assets of each core record")
    yield ("narrowing the listing to a question keeps what the dropped fact types said",
           "Identification" in narrowed and "income.emplcoreref" in narrowed
           and "Order " not in narrowed.split("Identification", 1)[-1]
                                       .split("Predicate readings", 1)[0],
           "Core's spellings kept, Order's lines dropped with Order")

    # -- rule 1d ----------------------------------------------------------------------------
    preferred, applied = derive(conn, path, prefer=True)
    yield ("rule 1d fires where the key is unreferenced and one other column is referenced",
           [(t, k, c) for t, k, c, _, _ in applied] == [("orders", "orderspivot",
                                                         "recordvault")],
           "applied %s" % [(t, k, c) for t, k, c, _, _ in applied])
    yield ("not where the referenced column repeats -- a declared key the rows refute",
           all(t != "batch" for t, *_ in applied), "batch.lot: 9 distinct over %d" % ROWS)
    yield ("not where it is sometimes absent -- an instance it cannot name",
           all(t != "depot" for t, *_ in applied), "depot.code: one NULL")
    yield ("and not where the key is what is referenced",
           all(t != "flow" for t, *_ in applied), "flow.recordregistry")
    after = driver.identification(preferred)["et.Order"]
    yield ("the referenced column becomes the identifier and the declared key the alternate",
           after["by"] == ["OrderRecordvault"]
           and after["referenced"] == ["fee.orderslink", "margin.ordervault"]
           and ("OrderSpivot", [], True) in after["also"],
           "Order by %s, also %s" % (after["by"], after["also"]))
    yield ("a foreign key onto it is then an ordinary one",
           not any(rm.get("references") for rm in preferred["mapping"]["roleMap"]
                   if "orders" in rm["table"] or "Order" in rm["role"]),
           "no role into Order carries `references`")
    # The identity changed and no fact did: every query that reads values says what it said.
    for query in ("LIST v, a FROM Fee has FeeAmt a AND ALSO has Order has OrderRecordvault v",
                  "LIST p, q FROM Order has OrderSpivot p AND ALSO has OrderQty q",
                  "LIST v, n FROM Margin m has Order has OrderRecordvault v "
                  "AND ALSO THE COUNT OF m GROUPED BY v AS n"):
        before, now = rows(model, conn, query), rows(preferred, conn, query)
        yield ("rule 1d leaves the facts alone: %s" % query[:44],
               before == now and len(now) > 0, "%d row(s) both ways" % len(now))
    yield ("and a denotation now names an order the way the schema does",
           rows(preferred, conn, "LIST q FROM Order: 'OB0500' has OrderQty q") == [(0,)],
           "Order: 'OB0500' is the order with qty 0")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    path = tempfile.mktemp(suffix=".sqlite")
    conn = build(path)
    passed = failed = 0
    try:
        for name, ok, note in cases(conn, path):
            if args.only and args.only.lower() not in name.lower():
                continue
            if ok:
                passed += 1
                if args.verbose:
                    print("ok    %-60s %s" % (name[:60], note))
            else:
                failed += 1
                print("FAIL  %s\n        %s" % (name, note))
    finally:
        conn.close()
        os.remove(path)
    print("\n%d passed, %d failed, %d total" % (passed, failed, passed + failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
