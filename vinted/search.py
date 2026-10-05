"""/vinted/search* — the catalogue search with every filter the site has,
the filter options (with live item counts) that apply to a search, and the
search box's suggestions.

Vinted serves at most 960 results per search (10 pages of 96): page 11 is
an upstream 400, and `total_count` stops at 960 however many items match.
Reaching deeper means narrowing — a category, a brand, a size or a price
band each gets its own 960.
"""
from vinted import countries, refs
from vinted import parsers as P
from vinted.fetch import gateway, gather
from vinted.shared import market

# public list param -> gateway filter code (attribute_ids[<code>]=id,id)
_LIST_PARAMS = (("category_ids", "catalog"), ("brand_ids", "brand"), ("size_ids", "size"),
                ("condition_ids", "status"), ("color_ids", "color"),
                ("material_ids", "material"), ("pattern_ids", "patterns"))
_CODE_TO_PARAM = {code: param for param, code in _LIST_PARAMS}


def _resolve(query, country, language, min_price, max_price, lists, filters):
    """Fold a catalog link passed as `query` into the explicit params
    (explicit values win) -> (country, language, text, price range,
    {filter code: [ids]}, link parts)."""
    link = {}
    text = query
    if query and refs.is_link(query):
        try:
            link = refs.parse_search_link(query)
        except ValueError:
            raise ValueError("query must be search text or a Vinted catalog link "
                             "(https://www.vinted.fr/catalog?search_text=nike&brand_ids[]=53)")
        text = link.get("query")
    country, language = market(country, language, link.get("country"))
    selected = {code: list(ids) for code, ids in (link.get("filters") or {}).items()}
    for param, code in _LIST_PARAMS:
        if lists.get(param):
            selected[code] = list(lists[param])
    for code, ids in (filters or {}).items():
        selected[_alias(code)] = list(ids)
    low = min_price if min_price is not None else link.get("min_price")
    high = max_price if max_price is not None else link.get("max_price")
    return country, language, text, low, high, selected, link


def _alias(code):
    """Accept the public names inside `filters` too (condition:6, category:5)."""
    return {"condition": "status", "category": "catalog", "colour": "color",
            "pattern": "patterns"}.get(code, code)


def _upstream(text, low, high, selected, country):
    params = {"search_text": text}
    if low is not None:
        params["price_from"] = _number(low)
    if high is not None:
        params["price_to"] = _number(high)
    if low is not None or high is not None:
        params["currency"] = countries.currency(country)
    for code, ids in selected.items():
        params[f"attribute_ids[{code}]"] = ",".join(ids)
    return params


def _number(value):
    return int(value) if float(value).is_integer() else value


def _applied(selected):
    """Echo of the filters that were applied, under their public names."""
    out = {}
    for code, ids in selected.items():
        if code in _CODE_TO_PARAM:
            out[_CODE_TO_PARAM[code]] = list(ids)
        else:
            out.setdefault("filters", {})[code] = list(ids)
    return out


def search(query=None, country=None, language=None, sort_by=None, page=None, per_page=48,
           min_price=None, max_price=None, category_ids=None, brand_ids=None, size_ids=None,
           condition_ids=None, color_ids=None, material_ids=None, pattern_ids=None, filters=None):
    lists = {"category_ids": category_ids, "brand_ids": brand_ids, "size_ids": size_ids,
             "condition_ids": condition_ids, "color_ids": color_ids,
             "material_ids": material_ids, "pattern_ids": pattern_ids}
    country, language, text, low, high, selected, link = _resolve(
        query, country, language, min_price, max_price, lists, filters)
    page = page or link.get("page") or 1
    if page * per_page > 960:
        raise ValueError("Vinted serves the first 960 results of a search: page x per_page must not exceed 960")
    sort_by = sort_by or link.get("sort_by") or "relevance"

    params = _upstream(text, low, high, selected, country)
    params.update({"page": page, "per_page": per_page, "order": sort_by})
    body = gateway(country, "/svc-catalogue/items", params, language=language, label="search") or {}
    items = P.item_cards(body.get("items"), country)
    return {
        "query": text,
        "country": country.upper(),
        "currency": countries.currency(country),
        "sort_by": sort_by,
        "min_price": low,
        "max_price": high,
        "applied_filters": _applied(selected),
        "pagination": P.pagination(body.get("pagination"), page, per_page),
        "items": items,
    }


def filters(query=None, country=None, language=None, min_price=None, max_price=None,
            category_ids=None, brand_ids=None, size_ids=None, condition_ids=None,
            color_ids=None, material_ids=None, pattern_ids=None, filters=None):
    """Every filter that applies to a search (they depend on the category:
    phones get Model / Storage / SIM lock, clothes get Size / Material /
    Pattern) with its options and how many matching items each option has."""
    lists = {"category_ids": category_ids, "brand_ids": brand_ids, "size_ids": size_ids,
             "condition_ids": condition_ids, "color_ids": color_ids,
             "material_ids": material_ids, "pattern_ids": pattern_ids}
    country, language, text, low, high, selected, _ = _resolve(
        query, country, language, min_price, max_price, lists, filters)
    params = _upstream(text, low, high, selected, country)

    body = gateway(country, "/svc-filters/filters", params, language=language, label="search filters") or {}
    rows = [r for r in (body.get("filters") if isinstance(body.get("filters"), list) else []) if isinstance(r, dict)]
    lazy = [r["code"] for r in rows if r.get("code") and r.get("code") != "price" and not r.get("options")]

    calls = {code: (lambda code=code: gateway(country, "/svc-filters/filters/facets",
                                              dict(params, filter_code=code), language=language,
                                              label=f"filter {code}"))
             for code in lazy}
    calls["__categories"] = lambda: gateway(country, "/svc-filters/faceted_categories", params,
                                            language=language, label="filter categories")
    parts = gather(calls, optional=list(calls))

    out = []
    categories = [c for c in (P.faceted_category(r, country) for r in
                              ((parts.get("__categories") or {}).get("categories") or [])) if c]
    if categories:
        out.append({"code": "catalog", "name": "Category", "search_param": "category_ids",
                    "search_param_format": None, "is_multi_select": True, "options": categories})
    for row in rows:
        facet = parts.get(row.get("code"))
        options = facet.get("options") if isinstance(facet, dict) else None
        parsed = P.search_filter(row, options)
        if parsed:
            out.append(parsed)
    return {
        "query": text,
        "country": country.upper(),
        "currency": countries.currency(country),
        "applied_filters": _applied(selected),
        "count": len(out),
        "filters": out,
    }


def autocomplete(query, country=None, language=None):
    """What the search box suggests while typing."""
    country, language = market(country, language)
    body = gateway(country, "/search-bar/v2/suggestions", {"search_text": query},
                   language=language, label="suggestions") or {}
    rows = [s for s in (P.suggestion(r) for r in (body.get("results") or [])) if s]
    return {"query": query, "country": country.upper(), "count": len(rows), "suggestions": rows}
