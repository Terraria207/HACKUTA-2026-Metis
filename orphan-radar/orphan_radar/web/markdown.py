"""A small Markdown renderer for briefs (headings, lists, quotes, tables, code, links, footnotes).
All text is escaped first; only the constructs below become HTML."""
from __future__ import annotations

import html
import re


def _inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[\^(\d+)\]", r'<sup><a href="#fn\1" id="r\1">\1</a></sup>', t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2))}" rel="noopener noreferrer" target="_blank">{m.group(1)}</a>', t)
    t = re.sub(r"&lt;(https?://[^&\s]+)&gt;", lambda m: f'<a href="{m.group(1)}" rel="noopener noreferrer" target="_blank">{m.group(1)}</a>', t)
    return t


def render(md: str) -> str:
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("<!--"):
            i += 1; continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1; continue
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            n = len(m.group(1)); out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>"); i += 1; continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[-| ]+\|$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[1:]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table>")
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip()); i += 1
            out.append("<blockquote>" + "<br>".join(_inline(b) for b in buf if b) + "</blockquote>")
            continue
        if re.match(r"^\s*- ", line):
            out.append("<ul>")
            while i < len(lines) and re.match(r"^\s*- ", lines[i]):
                indent = "nested" if lines[i].startswith("  ") else ""
                out.append(f'<li class="{indent}">{_inline(re.sub(r"^\s*- ", "", lines[i]))}</li>'); i += 1
            out.append("</ul>")
            continue
        m = re.match(r"^\[\^(\d+)\]: (.*)$", line)
        if m:
            out.append(f'<p class="fn" id="fn{m.group(1)}"><a href="#r{m.group(1)}">{m.group(1)}</a>. {_inline(m.group(2))}</p>'); i += 1; continue
        if line.strip():
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    return "\n".join(out)
