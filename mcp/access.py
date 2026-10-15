"""What a caller of the MCP server may see: the tables and columns it is allowed, removed from
the model before anything reads it, and refused by the connection that runs its queries.

A description narrowed to a question is a description an agent trusts to be the database, and
one built from every table describes data the caller cannot read -- the names of the tables,
the values the profile found in them, the relationships to them. So the restriction is
applied to the *model*, before linking scores a single concept: a hidden table is absent from
the description, not ranked low in it, and the narrowed view's "left out" list never names it
(schemagate does the same, filtering before scoring; its README says why).

Configured per database in the server's config, by whoever runs the server:

    "tables": ["employee", "department"]      only these; everything else is hidden
    "hide":   ["audit_log", "employee.salary"]  these tables, or these columns
    "role":   "analyst"                         PostgreSQL: SET ROLE, and hide whatever
                                                the role has no SELECT privilege on

Enforcement is the database's, not this module's. A SQLite connection gets an authorizer that
refuses a read of anything hidden -- through a view too, since SQLite authorizes the view's
own reads -- and of the catalogue and the pragmas, which would list it. A PostgreSQL
connection runs as the role, so the server refuses what the role may not read and row-level
security filters the rows -- but only if the DSN *logs in* as the role. `SET ROLE` after
connecting is undone by the caller's own `RESET ROLE` or `set_config('role', ...)`, so with
a privileged login it narrows the description and enforces nothing. What this module adds on PostgreSQL is the description: the model
was profiled from every row, so on a table under a row-level policy the value domains and
cautions are dropped. Some came from rows the role may not see, and the model does not say
which: a domain from a CHECK constraint goes too, which costs a filter's spelling, not a leak.

The server speaks stdio to one client and has no notion of who that client is; the identity
is the configuration's. A server per role is how to serve several.
"""

import json
import re
import sqlite3

CATALOGUE = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}


class AccessError(Exception):
    """The restriction could not be worked out. Nothing is described or run: a description
    that silently fell back to everything would be the leak this exists to prevent."""


class Access:
    def __init__(self, tables=None, hide=(), rls=()):
        self.tables = None if tables is None else {t.casefold() for t in tables}
        self.hidden_tables, self.hidden_columns = set(), set()
        for h in hide:
            t, _, c = h.casefold().partition(".")
            (self.hidden_columns.add((t, c)) if c else self.hidden_tables.add(t))
        self.rls = {t.casefold() for t in rls}

    @property
    def restricted(self):
        return self.tables is not None or bool(self.hidden_tables or self.hidden_columns)

    def table_ok(self, table):
        t = (table or "").casefold()
        return t not in self.hidden_tables and (self.tables is None or t in self.tables)

    def column_ok(self, table, column):
        return self.table_ok(table) and \
            ((table or "").casefold(), (column or "").casefold()) not in self.hidden_columns

    def signature(self):
        return json.dumps([sorted(self.tables) if self.tables is not None else None,
                           sorted(self.hidden_tables), sorted(self.hidden_columns),
                           sorted(self.rls)])

    # ------------------------------------------------------------------ enforcement

    def authorizer(self, action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ:
            if (arg1 or "").casefold() in CATALOGUE:
                return sqlite3.SQLITE_DENY
            if not self.column_ok(arg1, arg2) if arg2 else not self.table_ok(arg1):
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def guard(self, conn):
        """Make a SQLite connection refuse what is hidden. A no-op when nothing is."""
        if self.restricted:
            conn.set_authorizer(self.authorizer)
        return conn

    # ------------------------------------------------------------------ the model

    def restrict(self, model):
        """The model with every hidden table and column taken out, and everything that
        depends on them: the fact types they carry, the types that live only there, the
        constraints over those roles, and any free text that names them."""
        if not self.restricted and not self.rls:
            return model
        mapping = model.get("mapping") or {}
        tname = {t["id"]: t["name"] for t in mapping.get("tables", [])}
        tables = [t for t in mapping.get("tables", []) if self.table_ok(t["name"])]
        kept_t = {t["id"] for t in tables}
        columns = [c for c in mapping.get("columns", [])
                   if c["table"] in kept_t and self.column_ok(tname[c["table"]], c["name"])]
        kept_c = {c["id"] for c in columns}

        def fits(m):
            return m.get("table") in kept_t and all(
                c in kept_c for k in ("columns", "references", "identifyingColumns")
                for c in m.get(k) or [])

        role_map = [rm for rm in mapping.get("roleMap", []) if fits(rm)]
        mapped_roles = {rm["role"] for rm in role_map}
        placed = {m["concept"]: m for m in mapping.get("conceptMap", [])}
        concepts = model.get("concepts", [])

        gone = set()
        for c in concepts:
            if c["kind"] == "entity" and c["id"] in placed and not fits(placed[c["id"]]):
                gone.add(c["id"])
        all_mapped = {rm["role"] for rm in mapping.get("roleMap", [])}
        for c in concepts:
            if c["kind"] != "fact":
                continue
            roles = c.get("roles", [])
            if any(r["id"] in all_mapped and r["id"] not in mapped_roles for r in roles) or \
                    any(r["player"] in gone for r in roles) or \
                    (c["id"] in placed and not fits(placed[c["id"]])):
                gone.add(c["id"])
        played = {r["player"] for c in concepts if c["kind"] == "fact" and c["id"] not in gone
                  for r in c.get("roles", [])}
        for c in concepts:
            if c["kind"] == "value" and c["id"] not in played:
                gone.add(c["id"])
        dropped_roles = {r["id"] for c in concepts if c["id"] in gone
                         for r in c.get("roles", [])}

        hidden_names = sorted({n.casefold() for i, n in tname.items() if i not in kept_t} |
                              {c["name"].casefold() for c in mapping.get("columns", [])
                               if c["id"] not in kept_c and
                               not any(c["name"].casefold() == k["name"].casefold()
                                       for k in columns)}, key=len, reverse=True)
        mentions = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, hidden_names)),
                              re.IGNORECASE) if hidden_names else None
        rls_tables = {i for i, n in tname.items() if n.casefold() in self.rls}
        in_rls = {rm["role"] for rm in role_map if rm["table"] in rls_tables}

        out_concepts = []
        for c in concepts:
            if c["id"] in gone:
                continue
            c = json.loads(json.dumps(c))
            if c.get("supertypes"):
                c["supertypes"] = [s for s in c["supertypes"] if s not in gone]
            if c.get("identifier"):
                c["identifier"] = [r for r in c["identifier"] if r not in dropped_roles]
            if c["kind"] == "value" and any(r["player"] == c["id"] and r["id"] in in_rls
                                            for f in concepts if f["kind"] == "fact"
                                            for r in f.get("roles", [])):
                # profiled from every row; this role sees some of them
                c.pop("dataQuality", None)
                if c.get("restriction", {}).get("values"):
                    c.pop("restriction")
            if mentions:
                if c.get("dataQuality"):
                    c["dataQuality"] = [d for d in c["dataQuality"]
                                        if not mentions.search(json.dumps(d))]
                    if not c["dataQuality"]:
                        c.pop("dataQuality")
                if c.get("description") and mentions.search(c["description"]):
                    c.pop("description")
            out_concepts.append(c)

        ids = {c["id"] for c in out_concepts}
        constraints = [k for k in model.get("constraints", [])
                       if not (set(_refs(k)) & (dropped_roles | gone))]
        out = dict(model, concepts=out_concepts, constraints=constraints)
        for key in ("derivationRules", "macros", "queries"):
            if key in model:
                out[key] = [x for x in model[key]
                            if not (set(_refs(x)) & gone) and
                            not (mentions and mentions.search(json.dumps(x)))]
        if mapping:
            out["mapping"] = dict(
                mapping, tables=tables, columns=columns, roleMap=role_map,
                conceptMap=[m for m in mapping.get("conceptMap", [])
                            if m["concept"] in ids and fits(m)])
        return out


def _refs(x):
    """Every string inside a JSON value: the ids it can refer to."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _refs(v)
    elif isinstance(x, list):
        for v in x:
            yield from _refs(v)


def from_entry(entry, model=None, conn=None):
    """The Access a config entry asks for. A `role` is read from the database, as the role:
    which mapped tables and columns it may SELECT, and which tables have row-level security
    on. Raises AccessError rather than guess."""
    tables, hide = entry.get("tables"), list(entry.get("hide") or [])
    if not entry.get("role"):
        return Access(tables, hide)
    if conn is None or model is None:
        raise AccessError("role %r needs the model and a connection to read its privileges"
                          % entry["role"])
    mapping = model.get("mapping") or {}
    tname = {t["id"]: t for t in mapping.get("tables", [])}
    allowed, rls = [], []
    try:
        for tid, t in sorted(tname.items()):
            qual = '"%s"' % t["name"].replace('"', '""')
            if t.get("schema"):
                qual = '"%s".%s' % (t["schema"].replace('"', '""'), qual)
            whole = conn.execute("SELECT has_table_privilege(?, 'SELECT')", (qual,)).fetchone()[0]
            cols = [c for c in mapping.get("columns", [])
                    if c["table"] == tid and not c.get("path") and not c.get("isRowId")]
            if whole:
                allowed.append(t["name"])
            else:
                some = [c for c in cols if conn.execute(
                    "SELECT has_column_privilege(?, ?, 'SELECT')",
                    (qual, c["name"])).fetchone()[0]]
                if not some:
                    continue
                allowed.append(t["name"])
                hide += ["%s.%s" % (t["name"], c["name"]) for c in cols if c not in some]
            secured = conn.execute(
                "SELECT relrowsecurity FROM pg_class WHERE oid = ?::regclass", (qual,)
            ).fetchone()
            if secured and secured[0]:
                rls.append(t["name"])
    except Exception as e:                                          # noqa: BLE001
        raise AccessError("could not read the privileges of role %r: %s" % (entry["role"], e))
    if tables is not None:
        allowed = [t for t in allowed if t.casefold() in {x.casefold() for x in tables}]
    return Access(allowed, hide, rls)
