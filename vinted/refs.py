"""Vinted reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrIdField convention — never a sibling `url`/`id` pair).

  item      10252963967 | 10252963967-501-premium-quality
            | https://www.vinted.fr/items/10252963967-501-premium-quality
  seller    3146217014 | moniquevintage78 (username)
            | https://www.vinted.fr/member/3146217014-moniquevintage78
  brand     53 | https://www.vinted.fr/brand/53-nike
  category  1206 | https://www.vinted.fr/catalog/1206-outerwear
  query     free text | any vinted catalog link
            (https://www.vinted.fr/catalog?search_text=nike&brand_ids[]=53&price_to=20)

A link also names its country site (vinted.co.uk -> GB); resolvers return
it as `country` so an endpoint can default to the link's own market.
"""
import re
from urllib.parse import parse_qsl, quote, urlparse

from vinted import countries

_ID_RE = re.compile(r"^\d{1,15}$")
_ID_SLUG_RE = re.compile(r"^(\d{1,15})(?:-[^/]*)?$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{2,40}$")
_HOST_RE = re.compile(r"^(?:www\.)?vinted\.[a-z.]{2,6}(?=/|$)", re.I)

# site query key -> gateway filter code (attribute_ids[<code>])
_LINK_FILTERS = {
    "catalog": "catalog", "catalog_ids": "catalog",
    "brand_ids": "brand", "size_ids": "size", "status_ids": "status",
    "color_ids": "color", "material_ids": "material", "patterns_ids": "patterns",
}
SORT_ORDERS = ("relevance", "newest_first", "price_low_to_high", "price_high_to_low")


def is_link(value):
    value = str(value or "").strip()
    return value.startswith(("http://", "https://", "//")) or bool(_HOST_RE.match(value))


def _parse(value):
    """A vinted link -> (country code, path segments, query pairs). Raises
    ValueError for another site."""
    url = value.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    country = countries.country_of_host(parsed.hostname)
    if country is None:
        raise ValueError("not a vinted link")
    segments = [s for s in parsed.path.split("/") if s]
    return country, segments, parse_qsl(parsed.query, keep_blank_values=False)


def _id_after(segments, marker):
    for index, segment in enumerate(segments[:-1]):
        if segment.lower() == marker:
            match = _ID_SLUG_RE.match(segments[index + 1])
            if match:
                return match.group(1)
    return None


# ---- links out -----------------------------------------------------------------

def absolute(country, path):
    """A site-relative path or any vinted URL -> absolute link on the
    country's own host."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("http"):
        parsed = urlparse(path)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if not path.startswith("/"):
        path = "/" + path
    return countries.site(country) + path


def item_link(country, item_id):
    return f"{countries.site(country)}/items/{item_id}" if item_id else None


def seller_link(country, seller_id, username=None):
    if not seller_id:
        return None
    slug = f"-{quote(username, safe='')}" if username else ""
    return f"{countries.site(country)}/member/{seller_id}{slug}"


def brand_link(country, brand_id, slug=None):
    if not brand_id:
        return None
    return f"{countries.site(country)}/brand/{brand_id}" + (f"-{slug}" if slug else "")


def category_link(country, category_id):
    return f"{countries.site(country)}/catalog/{category_id}" if category_id else None


# ---- resolvers -------------------------------------------------------------------

def resolve_item(value):
    """Item id or a vinted item link -> {"id": "10252963967", "country": "fr"|None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("item is required")
    country = None
    if is_link(value):
        try:
            country, segments, _ = _parse(value)
        except ValueError:
            raise ValueError("item must be a Vinted item link (https://www.vinted.fr/items/10252963967-...) or an item id")
        item_id = _id_after(segments, "items")
        if not item_id:
            raise ValueError("item link must look like https://www.vinted.fr/items/10252963967-...")
        return {"id": item_id, "country": country}
    match = _ID_SLUG_RE.match(value)
    if not match:
        raise ValueError("item must be a numeric Vinted item id or a Vinted item link")
    return {"id": match.group(1), "country": country}


def resolve_seller(value):
    """Member id, username or a vinted profile link ->
    {"id": "3146217014"|None, "username": "name"|None, "country": "fr"|None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("seller is required")
    if is_link(value):
        try:
            country, segments, _ = _parse(value)
        except ValueError:
            raise ValueError("seller must be a Vinted profile link (https://www.vinted.fr/member/3146217014-name), a member id or a username")
        member_id = _id_after(segments, "member")
        if not member_id:
            raise ValueError("seller link must look like https://www.vinted.fr/member/3146217014-name")
        return {"id": member_id, "username": None, "country": country}
    value = value.lstrip("@")
    if _ID_RE.match(value):
        return {"id": value, "username": None, "country": None}
    match = _ID_SLUG_RE.match(value)          # "3146217014-moniquevintage78"
    if match and len(match.group(1)) >= 5:
        return {"id": match.group(1), "username": None, "country": None}
    if not _USERNAME_RE.match(value):
        raise ValueError("seller must be a Vinted member id, a username or a profile link")
    return {"id": None, "username": value.lower(), "country": None}


def resolve_brand(value):
    """Brand id or a vinted brand link -> {"id": "53", "country": "fr"|None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("brand is required")
    if is_link(value):
        try:
            country, segments, _ = _parse(value)
        except ValueError:
            raise ValueError("brand must be a Vinted brand link (https://www.vinted.fr/brand/53-nike) or a brand id")
        brand_id = _id_after(segments, "brand")
        if not brand_id:
            raise ValueError("brand link must look like https://www.vinted.fr/brand/53-nike")
        return {"id": brand_id, "country": country}
    match = _ID_SLUG_RE.match(value)
    if not match:
        raise ValueError("brand must be a numeric Vinted brand id (find it with /vinted/brands/search) or a brand link")
    return {"id": match.group(1), "country": None}


def resolve_category(value):
    """Category id or a vinted catalog link -> the id string."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("category is required")
    if is_link(value):
        try:
            _, segments, _ = _parse(value)
        except ValueError:
            raise ValueError("category must be a Vinted catalog link (https://www.vinted.fr/catalog/1206-outerwear) or a category id")
        category_id = _id_after(segments, "catalog")
        if not category_id:
            raise ValueError("category link must look like https://www.vinted.fr/catalog/1206-outerwear")
        return category_id
    match = _ID_SLUG_RE.match(value)
    if not match:
        raise ValueError("category must be a numeric Vinted category id (see /vinted/categories) or a catalog link")
    return match.group(1)


def parse_search_link(value):
    """A vinted catalog / brand / search link -> {"country", "query",
    "sort_by", "min_price", "max_price", "page", "filters": {code: [ids]}}
    (absent parts are None / empty). Raises ValueError for another site."""
    country, segments, pairs = _parse(value)
    filters = {}

    def add(code, raw):
        for part in str(raw).split(","):
            part = part.strip()
            if _ID_RE.match(part) and part not in filters.setdefault(code, []):
                filters[code].append(part)

    category_id = _id_after(segments, "catalog")
    if category_id:
        add("catalog", category_id)
    brand_id = _id_after(segments, "brand")
    if brand_id:
        add("brand", brand_id)

    out = {"country": country, "query": None, "sort_by": None, "min_price": None,
           "max_price": None, "page": None, "filters": filters}
    for key, raw in pairs:
        key = key[:-2] if key.endswith("[]") else key
        if key == "search_text":
            out["query"] = " ".join(raw.split()) or None
        elif key == "order" and raw in SORT_ORDERS:
            out["sort_by"] = raw
        elif key in ("price_from", "price_to"):
            try:
                out["min_price" if key == "price_from" else "max_price"] = float(raw)
            except ValueError:
                pass
        elif key == "page" and raw.isdigit() and int(raw) >= 1:
            out["page"] = int(raw)
        elif key in _LINK_FILTERS:
            add(_LINK_FILTERS[key], raw)
        elif key.endswith("_ids") and re.match(r"^[a-z_]+_ids$", key):
            add(key[:-4], raw)                 # dynamic filters: video_game_platform_ids[] ...
    for code in [c for c, ids in filters.items() if not ids]:
        del filters[code]
    return out
