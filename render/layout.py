"""Layout for an ORM diagram: where the object types and fact types go.

Deterministic force-directed placement (Fruchterman-Reingold with a fixed seed), so the same
model always draws the same picture. Object types are the nodes. A binary fact type is an
edge between its two role players; an n-ary fact type gets a hub node so its role boxes have
somewhere to sit.

Reverse-engineered schemas are dominated by attribute fact types -- Chinook has 53 value
types to 10 entity types -- so value types are placed close to their entity and repel each
other weakly. Without that they form a ring at the diagram's edge and every attribute line
crosses the middle.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple


class Node:
    __slots__ = ("id", "kind", "x", "y", "dx", "dy", "w", "h")

    def __init__(self, nid, kind, x, y, w, h):
        self.id, self.kind = nid, kind
        self.x, self.y, self.w, self.h = x, y, w, h
        self.dx = self.dy = 0.0


def measure(name: str, refmode: str = "") -> Tuple[float, float]:
    width = max(84.0, 8.2 * len(name) + 26)
    if refmode:
        width = max(width, 8.2 * (len(refmode) + 2) + 26)
    return width, 46.0 if refmode else 38.0


def build(model: dict, show_values: bool = True) -> Dict:
    concepts = {c["id"]: c for c in model["concepts"]}

    def is_value(cid):
        return concepts[cid]["kind"] == "value"

    facts = []
    for c in model["concepts"]:
        if c["kind"] != "fact" or c.get("isImplied"):
            continue
        players = [r["player"] for r in c["roles"]]
        if not show_values and any(is_value(p) for p in players):
            continue
        facts.append(c)

    used = set()
    for f in facts:
        used.update(r["player"] for r in f["roles"])
    for c in model["concepts"]:
        if c.get("supertypes"):
            used.add(c["id"])
            used.update(c["supertypes"])
    for c in model["concepts"]:
        if c["kind"] == "entity" and c["id"] not in used:
            used.add(c["id"])

    rng = random.Random(20260906)
    nodes: Dict[str, Node] = {}
    for cid in sorted(used):
        c = concepts[cid]
        w, h = measure(c["name"], c.get("referenceMode", ""))
        angle = rng.random() * math.tau
        radius = 240 + rng.random() * 120
        nodes[cid] = Node(cid, c["kind"], math.cos(angle) * radius,
                          math.sin(angle) * radius, w, h)

    # n-ary fact types get a hub node to hang their role boxes on
    hubs: Dict[str, Node] = {}
    edges: List[Tuple[str, str, float]] = []
    for f in facts:
        players = [r["player"] for r in f["roles"] if r["player"] in nodes]
        if len(players) == 2:
            weight = 0.55 if any(is_value(p) for p in players) else 1.0
            edges.append((players[0], players[1], weight))
        elif len(players) >= 3:
            hub = Node("hub:" + f["id"], "hub", 0.0, 0.0, 10, 10)
            hubs[f["id"]] = hub
            nodes[hub.id] = hub
            hub.x = sum(nodes[p].x for p in players) / len(players)
            hub.y = sum(nodes[p].y for p in players) / len(players)
            for p in players:
                edges.append((hub.id, p, 1.0))
        elif len(players) == 1:
            pass                                    # unary: drawn on the object type itself

    for c in model["concepts"]:
        for sup in c.get("supertypes", []):
            if c["id"] in nodes and sup in nodes:
                edges.append((c["id"], sup, 1.6))

    # Fruchterman-Reingold needs a bounded frame or repulsion wins and the graph flies
    # apart -- badly so on small graphs, where nothing pulls back.
    area = max(1, len(nodes)) * 26000.0
    frame = math.sqrt(area)
    k = math.sqrt(area / max(1, len(nodes)))
    temperature = frame * 0.12
    # Everything the O(n^2) pass needs, resolved once rather than 420 times: the node list,
    # a parallel "is a value type" flag (the inner loop compared strings), the two repulsion
    # constants, and the edges as node pairs instead of id pairs.
    items = [nodes[i] for i in nodes]
    n_items = len(items)
    is_value = [n.kind == "value" for n in items]
    k2, k2_value = k * k, 0.45 * k * k
    edge_pairs = [(nodes[a], nodes[b], weight) for a, b, weight in edges]

    for _ in range(420):
        for n in items:
            n.dx = n.dy = 0.0
        for i in range(n_items):
            na = items[i]
            nax, nay = na.x, na.y
            adx = ady = 0.0
            a_is_value = is_value[i]
            for j in range(i + 1, n_items):
                nb = items[j]
                dx, dy = nax - nb.x, nay - nb.y
                d2 = dx * dx + dy * dy
                if d2 < 1e-6:
                    dx, dy, d2 = rng.random() - .5, rng.random() - .5, 1e-3
                d = math.sqrt(d2)
                # value types repel each other less, so they cluster near their entity
                force = (k2_value if (a_is_value and is_value[j]) else k2) / d
                fx, fy = dx / d * force, dy / d * force
                adx += fx; ady += fy
                nb.dx -= fx; nb.dy -= fy
            na.dx += adx; na.dy += ady
        for na, nb, weight in edge_pairs:
            dx, dy = na.x - nb.x, na.y - nb.y
            d = max(1e-3, math.hypot(dx, dy))
            force = (d * d) / k * weight
            fx, fy = dx / d * force, dy / d * force
            na.dx -= fx; na.dy -= fy
            nb.dx += fx; nb.dy += fy
        half = frame / 2
        for n in items:
            d = max(1e-3, math.hypot(n.dx, n.dy))
            n.x += n.dx / d * min(d, temperature)
            n.y += n.dy / d * min(d, temperature)
            n.x = max(-half, min(half, n.x))
            n.y = max(-half, min(half, n.y))
        temperature = max(frame * 0.002, temperature * 0.975)

    _separate(items)

    xs = [n.x - n.w / 2 for n in nodes.values()] + [n.x + n.w / 2 for n in nodes.values()]
    ys = [n.y - n.h / 2 for n in nodes.values()] + [n.y + n.h / 2 for n in nodes.values()]
    pad = 90
    minx, miny = min(xs) - pad, min(ys) - pad
    for n in nodes.values():
        n.x -= minx
        n.y -= miny
    width, height = max(xs) - minx + pad, max(ys) - miny + pad

    return {
        "nodes": {nid: {"x": round(n.x, 1), "y": round(n.y, 1),
                        "w": round(n.w, 1), "h": round(n.h, 1), "kind": n.kind}
                  for nid, n in nodes.items()},
        "hubs": {fid: hub.id for fid, hub in hubs.items()},
        "facts": [f["id"] for f in facts],
        "width": round(width, 1), "height": round(height, 1),
    }


def _separate(items, rounds: int = 90):
    """Push overlapping boxes apart. The force pass treats nodes as points; these are boxes."""
    for _ in range(rounds):
        moved = False
        for i, a in enumerate(items):
            for j in range(i + 1, len(items)):
                b = items[j]
                ox = (a.w + b.w) / 2 + 22 - abs(a.x - b.x)
                oy = (a.h + b.h) / 2 + 18 - abs(a.y - b.y)
                if ox > 0 and oy > 0:
                    moved = True
                    if ox < oy:
                        shift = ox / 2 * (1 if a.x >= b.x else -1)
                        a.x += shift; b.x -= shift
                    else:
                        shift = oy / 2 * (1 if a.y >= b.y else -1)
                        a.y += shift; b.y -= shift
        if not moved:
            break
