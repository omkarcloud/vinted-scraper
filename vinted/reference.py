"""/vinted/categories, /sizes, /colors, /conditions, /materials, /countries
— the id catalogues the /vinted/search filters take. Labels follow
`language`; ids are the same on every country site."""
from vinted import countries as C
from vinted import parsers as P
from vinted.fetch import VintedNotFound, api, gateway
from vinted.shared import TABLE_TTL, market, memo


def _tree(country, language):
    def build():
        body = api(country, "/item_upload/catalogs", language=language, label="categories") or {}
        return [c for c in (P.category(r, country) for r in (body.get("catalogs") or [])) if c]
    return memo(("categories", country, language), TABLE_TTL, build)


def _find(nodes, category_id):
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if node["id"] == category_id:
            return node
        stack.extend(node["children"])
    return None


def _count(nodes):
    return sum(1 + _count(n["children"]) for n in nodes)


def categories(country=None, language=None, category=None):
    """The whole category tree, or — with `category` — that node and
    everything under it."""
    country, language = market(country, language)
    tree = _tree(country, language)
    if category:
        node = _find(tree, category)
        if node is None:
            raise VintedNotFound(f"category '{category}' not found")
        return {"country": country.upper(), "count": 1 + _count(node["children"]), "category": node}
    return {"country": country.upper(), "count": _count(tree), "categories": tree}


def sizes(country=None, language=None):
    country, language = market(country, language)
    body = api(country, "/size_groups", language=language, label="sizes") or {}
    groups = [g for g in (P.size_group(r) for r in (body.get("size_groups") or [])) if g]
    return {"country": country.upper(), "count": len(groups), "size_groups": groups}


def colors(country=None, language=None):
    country, language = market(country, language)
    body = api(country, "/colors", language=language, label="colors") or {}
    rows = [c for c in (P.color(r) for r in (body.get("colors") or [])) if c]
    return {"country": country.upper(), "count": len(rows), "colors": rows}


def _facet(country, language, code, category=None):
    params = {"filter_code": code}
    if category:
        params["attribute_ids[catalog]"] = category
    body = gateway(country, "/svc-filters/filters/facets", params, language=language, label=code) or {}
    return [o for o in (P.simple_option(r) for r in (body.get("options") or [])) if o]


def conditions(country=None, language=None):
    country, language = market(country, language)
    rows = _facet(country, language, "status")
    return {"country": country.upper(), "count": len(rows), "conditions": rows}


def materials(country=None, language=None, category=None):
    """Material ids. The list depends on the category (fabrics for
    clothing, glass / wood / metal for home); without `category` it is the
    clothing set."""
    country, language = market(country, language)
    rows = [{"id": r["id"], "name": r["name"]} for r in _facet(country, language, "material", category)]
    return {"country": country.upper(), "category_id": category, "count": len(rows), "materials": rows}


def countries():
    """The Vinted country sites this API reads, with their currency and the
    languages each serves."""
    rows = C.table()
    return {"count": len(rows), "default_country": C.DEFAULT_COUNTRY.upper(),
            "default_language": C.DEFAULT_LANGUAGE, "countries": rows}
