"""/vinted/brands/* — brand lookup (name -> the id /vinted/search takes as
`brand_ids`) and one brand's listing / follower counts."""
from vinted import parsers as P
from vinted.fetch import VintedNotFound, api
from vinted.shared import market


def search(query, country=None, language=None):
    country, language = market(country, language)
    body = api(country, "/brands", {"keyword": query}, language=language, label="brand search") or {}
    rows = [b for b in (P.brand(r, country) for r in (body.get("brands") or [])) if b]
    return {"query": query, "country": country.upper(), "count": len(rows), "brands": rows}


def details(brand, country=None, language=None):
    country, language = market(country, language, brand.get("country"))
    brand_id = brand["id"]
    body = api(country, f"/brands/{brand_id}", language=language, label=f"brand {brand_id}") or {}
    parsed = P.brand(body.get("brand"), country)
    if not parsed:
        raise VintedNotFound(f"brand '{brand_id}' not found")
    return {"brand": parsed}
