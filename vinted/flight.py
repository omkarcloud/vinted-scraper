"""Next.js RSC "flight" payload reader for vinted item pages.

An item page ships its data as `self.__next_f.push([1, "<chunk>"])` script
tags. Joined, the chunks are rows of `<hex id>:<payload>`: JSON rows, and
text rows `<id>:T<hex byte length>,<raw text>` (long strings such as the
item description, referenced elsewhere as "$<id>"). Text rows may contain
newlines, so rows are read by length, not split on "\n".

The page content is a set of "plugins" — dicts shaped
{name, section, type, data} (gallery, attributes, description, breadcrumbs,
favourite, user_info_header, ...). plugins() returns {name: data} with
"$<id>" text references already resolved.
"""
import json
import re

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ROW_RE = re.compile(rb"([0-9a-f]+):")
_REF_RE = re.compile(r"^\$([0-9a-f]+)$")


def flight_rows(html):
    """Page HTML -> {row id: parsed JSON | text}. Unparseable rows are skipped."""
    parts = []
    for match in _PUSH_RE.finditer(html or ""):
        try:
            parts.append(json.loads(match.group(1)))
        except ValueError:
            continue
    data = "".join(parts).encode("utf-8", "surrogatepass")
    rows = {}
    pos, end = 0, len(data)
    while pos < end:
        match = _ROW_RE.match(data, pos)
        if not match:
            nxt = data.find(b"\n", pos)
            if nxt < 0:
                break
            pos = nxt + 1
            continue
        row_id = match.group(1).decode()
        pos = match.end()
        if data[pos:pos + 1] == b"T":
            comma = data.find(b",", pos)
            try:
                length = int(data[pos + 1:comma], 16)
            except ValueError:
                length = -1
            if comma > 0 and length >= 0:
                rows[row_id] = data[comma + 1:comma + 1 + length].decode("utf-8", "replace")
                pos = comma + 1 + length
                continue
        nxt = data.find(b"\n", pos)
        if nxt < 0:
            nxt = end
        raw = data[pos:nxt].decode("utf-8", "replace")
        pos = nxt + 1
        if raw[:1] in ("[", "{", '"'):
            try:
                rows[row_id] = json.loads(raw)
            except ValueError:
                pass
    return rows


def _walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _resolve(value, rows, depth=0):
    """Replace "$<id>" strings that point at TEXT rows with the text."""
    if isinstance(value, str):
        if value.startswith("$$"):
            return value[1:]              # flight escapes a literal leading "$" as "$$"
        match = _REF_RE.match(value)
        if match and isinstance(rows.get(match.group(1)), str):
            return rows[match.group(1)]
        return value
    if depth > 12:
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, rows, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, rows, depth + 1) for v in value]
    return value


def plugins(rows):
    """{plugin name: data dict}. A plugin can appear twice (sidebar + sticky
    copies); the copy with the most data keys wins."""
    out = {}
    for row in rows.values():
        if not isinstance(row, (dict, list)):
            continue
        for node in _walk(row):
            data = node.get("data")
            if isinstance(data, dict) and isinstance(node.get("name"), str) and "section" in node and "type" in node:
                name = node["name"]
                if name not in out or len(data) > len(out[name]):
                    out[name] = data
    return {name: _resolve(data, rows) for name, data in out.items()}


def ld_json(html, wanted_type="Product"):
    """The first <script type="application/ld+json"> object of `wanted_type`."""
    for match in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html or "", re.S):
        try:
            obj = json.loads(match.group(1))
        except ValueError:
            continue
        for node in obj if isinstance(obj, list) else [obj]:
            if isinstance(node, dict) and node.get("@type") == wanted_type:
                return node
    return None
