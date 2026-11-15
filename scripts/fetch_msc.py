#!/usr/bin/env python3
"""Fetch the official MSC 2020 table and write it as JSON for the indexer.

  python scripts/fetch_msc.py --output .lean/msc/msc2020.json

Source: https://msc2020.org/MSC_2020.csv, published jointly by Mathematical Reviews and zbMATH
under a Creative Commons CC BY-NC-SA licence. The table is therefore fetched, not committed:
check that licence against your use before redistributing a copy or a module built from it.
The design doc builds the group tree from MSC 2020 by script; this is that script's input.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from pathlib import Path

SOURCE = "https://msc2020.org/MSC_2020.csv"


TEX = {
    "\\{": "{", "\\}": "}", "\\'": "'", "\\(": "", "\\)": "", "$": "", "{}_2F_1": "2F1", "\\mbox{GL}": "GL",
    "\\infty": "∞", "\\dots": "…", "\\ne": "≠", "\\ge": "≥", "\\le": "≤", "\\overline\\partial": "∂̄", "\\partial": "∂",
    "\\mathbb{R}": "ℝ", "\\mathbb{C}": "ℂ", "\\mathbb{Z}": "ℤ", "\\mathbb{Q}": "ℚ", "\\mathbb{N}": "ℕ", "\\mathbb{P}": "ℙ",
    "\\Gamma": "Γ", "\\Delta": "Δ", "\\Lambda": "Λ", "\\Omega": "Ω", "\\Sigma": "Σ", "\\Pi": "Π", "\\Phi": "Φ",
    "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ", "\\epsilon": "ε", "\\varepsilon": "ε", "\\zeta": "ζ",
    "\\eta": "η", "\\theta": "θ", "\\kappa": "κ", "\\lambda": "λ", "\\mu": "μ", "\\nu": "ν", "\\pi": "π", "\\rho": "ρ",
    "\\sigma": "σ", "\\tau": "τ", "\\phi": "φ", "\\chi": "χ", "\\psi": "ψ", "\\omega": "ω",
}


def plain_text(title):
    """The table is written with a little TeX; turn the common pieces into plain text."""
    for tex in sorted(TEX, key=len, reverse=True):
        title = title.replace(tex, TEX[tex])
    title = re.sub(r"\\math[a-z]+\{([^}]*)\}", r"\1", title).replace("\\subset", "⊂")
    return " ".join(title.split())


def parse(raw, complete=True):
    """Rows are code, text, description; tab separated, Latin-1. Codes look like 05-XX (field),
    05Cxx (subfield), 05C50 (subtopic) and 05-01 (general material, which has no place in the
    field/subfield/subtopic tree and is left out)."""
    text = raw.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t", quotechar='"'))
    if rows[0][:2] != ["code", "text"]:
        raise ValueError("Unexpected MSC table header")
    fields, subfields, subtopics, general = {}, {}, {}, 0
    for row in rows[1:]:
        if len(row) < 2 or not row[0].strip():
            continue
        code, title = row[0].strip(), " ".join(row[1].split())
        title = plain_text(title)
        if len(code) != 5:
            raise ValueError("Unexpected MSC code " + code)
        if code.endswith("-XX"):
            fields[code[:2]] = title
        elif code.endswith("xx"):
            subfields[code[:3]] = title
        elif code[2] == "-":
            general += 1
        else:
            subtopics[code] = title
    if complete and not (len(fields) > 50 and len(subfields) > 400 and len(subtopics) > 5000):
        raise ValueError("MSC table looks incomplete")
    return {"fields": fields, "subfields": subfields, "subtopics": subtopics, "general_codes_left_out": general}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv", type=Path, help="Use an already downloaded MSC_2020.csv instead of fetching")
    args = parser.parse_args()
    raw = args.csv.read_bytes() if args.csv else urllib.request.urlopen(SOURCE, timeout=60).read()
    table = parse(raw)
    table.update(source=SOURCE, sha256=hashlib.sha256(raw).hexdigest(), retrieved=time.strftime("%Y-%m-%d"),
                 licence="CC BY-NC-SA (Mathematical Reviews and zbMATH); see https://msc2020.org/")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: len(table[k]) for k in ("fields", "subfields", "subtopics")} | {"output": str(args.output)}))


if __name__ == "__main__":
    main()
