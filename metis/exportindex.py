"""Basis groups from the data (overview, Base graph): the mathlib declaration export placed in the
MSC 2020 tree by script and split into one file per basis group.

A basis group is an MSC 2020 field (its two-digit class), with one exception kept from the design
doc's demo islands: graph theory (05C) is its own basis group and Combinatorics covers the rest
of 05. Which groups exist is decided by the data: every field that receives at least one
declaration is offered, none is hardcoded.

Placement is the recorded script heuristic in deploy/msc/mathlib-paths.txt (longest matching
module-path prefix -> MSC subtopic). The gods refine it in a curated build. Declarations whose
module matches no rule are counted and left out rather than guessed.
"""

import json
import os
import re
import time

FORMAT = "metis-export-index-1"
# Demo islands named in the design doc keep their ids and plain names; every other basis group
# takes its name from the MSC field title.
NAMED = {
    "11": ("number-theory", "Number theory"),
    "15": ("linear-algebra", "Linear algebra"),
    "60": ("probability", "Probability"),
    "05C": ("graph-theory", "Graph theory"),
    "05": ("combinatorics", "Combinatorics"),
}


def slug(title):
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return text if len(text) <= 48 else text[:48].rsplit("-", 1)[0]  # cut at a word, not mid-word


def load_rules(path):
    rules = {}
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 2 or not parts[0].startswith("Mathlib") or parts[0] in rules:
                raise ValueError("Bad placement rule on line %d of %s" % (number, path))
            rules[parts[0]] = parts[1]
    return rules


def check_rules(rules, msc):
    unknown = sorted({c for c in rules.values() if c != "-" and c not in msc["subtopics"]})
    if unknown:
        raise ValueError("Placement codes that are not MSC 2020 subtopics: " + ", ".join(unknown))


def place(module, rules):
    """Longest matching prefix. Returns an MSC subtopic code, "-" (deliberately left out) or None."""
    probe = module
    while probe:
        if probe in rules:
            return rules[probe]
        probe = probe.rpartition(".")[0]
    return None


def island_key(code):
    return "05C" if code.startswith("05C") else code[:2]


def island_meta(key, msc):
    field = msc["fields"][key[:2]]
    ident, name = NAMED.get(key, (slug(field), field))
    return {"id": ident, "name": name, "msc": key, "field": field}


def tree(key, msc):
    """The complete MSC subtree of a basis group, in the shape the module builder takes: field
    (depth 1), subfields (depth 2), subtopics (depth 3)."""
    subfields = []
    for sub in sorted(msc["subfields"]):
        if not sub.startswith(key[:2]) or (key == "05C") != (sub == "05C"):
            continue
        topics = [{"msc": c, "name": msc["subtopics"][c]} for c in sorted(msc["subtopics"]) if c.startswith(sub)]
        if topics:
            subfields.append({"msc": sub, "name": msc["subfields"][sub], "subtopics": topics})
    return {"field": {"msc": key[:2], "name": msc["fields"][key[:2]]}, "subfields": subfields}


def build_index(lines, msc, rules, output, mathlib, lean=None, rules_sha256=None):
    """Stream the JSONL export, place every declaration, and write index.json plus one file per
    basis group under output/islands/."""
    check_rules(rules, msc)
    islands, skipped, unplaced, total = {}, 0, {}, 0
    for line in lines:
        if not line.strip():
            continue
        d = json.loads(line)
        total += 1
        code = place(d["module"], rules)
        if code == "-":
            skipped += 1
            continue
        if code is None:
            top = ".".join(d["module"].split(".")[:2])
            unplaced[top] = unplaced.get(top, 0) + 1
            continue
        d["msc"] = code
        islands.setdefault(island_key(code), []).append(d)
    os.makedirs(os.path.join(output, "islands"), exist_ok=True)
    entries = []
    for key in sorted(islands):
        meta = island_meta(key, msc)
        declarations = sorted(islands[key], key=lambda d: d["name"])
        leaves = {d["msc"] for d in declarations}
        with open(os.path.join(output, "islands", meta["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump({"island": meta, "mathlib": mathlib, "lean": lean, "tree": tree(key, msc), "declarations": declarations}, f, ensure_ascii=False)
        entries.append(dict(meta, declarations=len(declarations), documented=sum(1 for d in declarations if (d.get("docstring") or "").strip()),
                            populated_subtopics=len(leaves), file="islands/" + meta["id"] + ".json"))
    index = {
        "format": FORMAT,
        "mathlib": mathlib,
        "lean": lean,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "msc": {k: msc.get(k) for k in ("source", "sha256", "retrieved", "licence")},
        "placement": {"rules": len(rules), "sha256": rules_sha256,
                      "method": "script: longest module-path prefix -> MSC 2020 subtopic; not gods-curated"},
        "totals": {"declarations": total, "placed": sum(e["declarations"] for e in entries), "left_out_as_tooling": skipped,
                   "unplaced": sum(unplaced.values()), "unplaced_by_area": dict(sorted(unplaced.items()))},
        "islands": entries,
    }
    with open(os.path.join(output, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    return index


_cache = {}


def load_index(path):
    """The export index, or None when `path` is not an index directory. Cached by file time."""
    if not path or not os.path.isdir(path):
        return None
    file = os.path.join(path, "index.json")
    try:
        stamp = os.path.getmtime(file)
    except OSError:
        return None
    if _cache.get(path, (None, None))[0] != stamp:
        with open(file, encoding="utf-8") as f:
            index = json.load(f)
        if index.get("format") != FORMAT:
            raise ValueError("Unrecognised export index format")
        _cache[path] = (stamp, index)
    return _cache[path][1]


def island_entry(path, island):
    index = load_index(path)
    return next((e for e in index["islands"] if e["id"] == island), None) if index else None


def load_island(path, island):
    """Declarations and MSC tree of one basis group, as a build spec plus its declarations."""
    entry = island_entry(path, island)
    if not entry:
        raise ValueError("The export has no declarations for " + str(island))
    file = os.path.normpath(os.path.join(path, entry["file"]))
    if not file.startswith(os.path.normpath(path) + os.sep):
        raise ValueError("Export index points outside its directory")
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
    spec = dict(data["tree"], island=entry["id"], name=entry["name"], msc=entry["msc"])
    return spec, data["declarations"], data["mathlib"], data.get("lean")
