#!/usr/bin/env python3
"""Render a Common Core Model as an ORM diagram in a self-contained HTML page.

    orm_render.py MODEL.ccm.json -o diagram.html
    orm_render.py MODEL.ccm.json -o diagram.html --compact   # open with value types hidden

The notation is ORM 2 as Halpin sets it out: entity types are soft rectangles, value types
are soft rectangles with a dashed outline, a fact type is a row of role boxes, a uniqueness
constraint is a bar over the roles it spans (doubled for a preferred identifier), a mandatory
role is a solid dot where the connector meets the object type, an objectified fact type is
framed and named, and a subtype is an arrow to its supertype.

Everything ships in the file: no network, no build step. Layout is precomputed by layout.py
so the page draws immediately and identically every time.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import layout as layout_mod   # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.ccm import Index    # noqa: E402

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")


def prepare(model: dict) -> dict:
    """Everything the page needs, resolved once here rather than in the browser."""
    ix = Index(model)
    roles, role_owner = ix.roles, ix.role_owner

    uniqueness = []
    for k in model.get("constraints", []):
        if k["kind"] != "uniqueness":
            continue
        for seq in k.get("roleSequences", []):
            if seq:
                uniqueness.append({"roles": seq,
                                   "preferred": bool(k.get("isPreferredIdentifier")),
                                   "internal": len({role_owner.get(r) for r in seq}) == 1})

    mapping = model.get("mapping") or {}
    tables = {t["id"]: t for t in mapping.get("tables", [])}
    columns = {c["id"]: c for c in mapping.get("columns", [])}
    concept_map, role_map = {}, {}
    for m in mapping.get("conceptMap", []):
        concept_map[m["concept"]] = {
            "table": tables.get(m["table"], {}).get("name", "?"),
            "columns": [columns.get(c, {}).get("name", "?")
                        for c in m.get("identifyingColumns", [])]}
    for m in mapping.get("roleMap", []):
        role_map[m["role"]] = {
            "table": tables.get(m["table"], {}).get("name", "?"),
            "columns": [columns.get(c, {}).get("name", "?") for c in m.get("columns", [])]}

    return {
        "name": model.get("name") or model.get("id"),
        "concepts": [
            {"id": c["id"], "name": c["name"], "kind": c["kind"],
             "referenceMode": c.get("referenceMode", ""),
             "supertypes": c.get("supertypes", []),
             "identifier": c.get("identifier", []),
             "isObjectified": bool(c.get("isObjectified")),
             "dataType": c.get("dataType"),
             "restriction": c.get("restriction"),
             # What the model says beyond its structure: the sentence a domain expert would
             # recognise (`description`, from a data dictionary or a knowledge base), and
             # what profiling the population found about the values (`dataQuality`). Neither
             # is a constraint and neither draws a mark, so both live in the inspector --
             # but leaving them out meant the diagram silently showed less than the model
             # knew, which is the one thing a picture of a schema must not do.
             "description": c.get("description", ""),
             "dataQuality": c.get("dataQuality", []),
             "roles": [{"id": r["id"], "player": r["player"],
                        "mandatory": bool(r.get("isMandatory")),
                        "name": r.get("name", "")} for r in c.get("roles", [])],
             "reading": ix.verbalise(c) if c["kind"] == "fact" else "",
             "map": concept_map.get(c["id"])}
            for c in model["concepts"]],
        "roleMap": role_map,
        "uniqueness": uniqueness,
        "layouts": {
            "full": layout_mod.build(model, show_values=True),
            "compact": layout_mod.build(model, show_values=False),
        },
    }


def render(model: dict, compact: bool = False) -> str:
    data = prepare(model)
    data["initialView"] = "compact" if compact else "full"
    with open(TEMPLATE_PATH, encoding="utf-8") as fh:
        template = fh.read()
    # The JSON lands inside a <script>, where the parser looks for "</script" before any
    # JavaScript runs. A table or column named like that would otherwise close the element
    # and inject the rest as markup, so escape the characters that could start a tag.
    payload = json.dumps(data, separators=(",", ":")) \
        .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace("/*__DATA__*/null", payload)


# The template is written to be publishable as an Artifact, where the host supplies the
# document skeleton. A file opened straight off disk gets none of that, and a browser left
# to guess the encoding renders UTF-8 as Latin-1.
STANDALONE = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
              '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
              '</head>\n<body>\n%s\n</body>\n</html>\n')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fragment", action="store_true",
                   help="emit the page body only, for publishing as an Artifact (the host "
                        "supplies doctype, charset and viewport)")
    p.add_argument("--compact", action="store_true",
                   help="open with value types hidden (entity-level view)")
    args = p.parse_args(argv)

    with open(args.model) as fh:
        model = json.load(fh)
    html = render(model, args.compact)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html if args.fragment else STANDALONE % html)

    counts = {}
    for c in model["concepts"]:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    print("%s -> %s  (%d entity, %d value, %d fact, %.0f KB)"
          % (args.model, args.out, counts.get("entity", 0), counts.get("value", 0),
             counts.get("fact", 0), len(html) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
