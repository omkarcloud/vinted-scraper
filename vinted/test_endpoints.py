"""Live endpoint smoke tests: one call per /vinted/* route against a running
service, with example values proven to return data (2026-10-05). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless VINTED_BASE points at a running service:

    ONLY_SCRAPER=vinted python run.py
    VINTED_BASE=http://127.0.0.1:6002 python -m pytest vinted/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("VINTED_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set VINTED_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def _live_item():
    """Listings are one-offs that sell, so item routes use a fresh one."""
    return call("/vinted/search", query="levis 501", per_page=5)["items"][0]


def test_search():
    page = call("/vinted/search", query="nike air max", per_page=10)
    assert len(page["items"]) == 10 and page["count"] > 100 and page["next"]
    first = page["items"][0]
    assert first["pricing"]["amount"] > 0 and first["pricing"]["currency"] == "EUR"
    assert first["link"].startswith("https://www.vinted.fr/items/") and first["seller"]["id"]
    # filters: Levi's (brand 10), new with / without tags, up to 40 EUR, cheapest first
    cheap = call("/vinted/search", query="jeans", brand_ids="10", condition_ids="6,1",
                 max_price=40, sort_by="price_low_to_high", per_page=5)
    assert cheap["items"] and all(i["pricing"]["amount"] <= 40 for i in cheap["items"])
    assert all(i["brand"] == "Levi's" for i in cheap["items"])
    # another market: prices in its own currency
    assert call("/vinted/search", query="nike", country="gb", per_page=3)["currency"] == "GBP"
    # a catalog link as the query carries its own site and filters
    linked = call("/vinted/search", per_page=3,
                  query="https://www.vinted.co.uk/catalog/5-men/brand/53-nike?search_text=air%20max&price_to=30")
    assert linked["country"] == "GB" and linked["applied_filters"]["brand_ids"] == ["53"]
    # category-specific filter: iPhone 11 (model 4041) in Mobile phones (3661)
    phones = call("/vinted/search", category_ids="3661", filters="brand_collection:4041", per_page=3)
    assert phones["items"]


def test_search_filters():
    body = call("/vinted/search/filters", query="iphone", category_ids="3661")
    codes = {f["code"] for f in body["filters"]}
    assert {"brand", "status", "brand_collection"} <= codes
    brand = next(f for f in body["filters"] if f["code"] == "brand")
    assert brand["search_param"] == "brand_ids" and brand["options"][0]["items_count"] > 0


def test_autocomplete():
    assert call("/vinted/autocomplete", query="lev")["suggestions"][0]["query"]


def test_items():
    card = _live_item()
    item = call("/vinted/items/details", item=card["id"])["item"]
    assert item["title"] and item["photos"] and item["category"]["path"]
    assert item["pricing"]["total_amount"] >= item["pricing"]["amount"] > 0
    assert item["seller"]["username"] and item["availability"]
    assert call("/vinted/items/details", item=card["link"])["item"]["id"] == card["id"]
    assert call("/vinted/items/similar", item=card["id"])["items"]
    shipping = call("/vinted/items/shipping", item=card["id"])
    assert shipping["buyer_protection"]["amount"] > 0 and shipping["pricing"]["currency"] == "EUR"


def test_sellers():
    seller = call("/vinted/sellers/details", seller="vintage")["seller"]
    assert seller["id"] == "28495914" and seller["feedback_count"] > 1000
    assert call("/vinted/sellers/details", seller="https://www.vinted.fr/member/28495914-vintage")["seller"]["username"] == "vintage"
    wardrobe = call("/vinted/sellers/items", seller="28495914", per_page=5)
    assert wardrobe["items"] and wardrobe["count"] > 5 and wardrobe["next"]
    feedback = call("/vinted/sellers/feedback", seller="28495914", type="member", per_page=5)
    assert feedback["feedback"][0]["text"] and feedback["summary"]["count"] > 1000
    assert call("/vinted/sellers/followers", seller="28495914", per_page=5)["sellers"]
    assert "sellers" in call("/vinted/sellers/following", seller="28495914", per_page=5)
    assert call("/vinted/sellers/search", query="vintage")["sellers"][0]["username"]


def test_brands():
    assert call("/vinted/brands/search", query="nike")["brands"][0]["id"] == "53"
    assert call("/vinted/brands/details", brand="53")["brand"]["items_count"] > 1_000_000
    assert call("/vinted/brands/details", brand="https://www.vinted.fr/brand/10-levis")["brand"]["name"] == "Levi's"


def test_reference():
    tree = call("/vinted/categories")
    assert tree["count"] > 1000 and tree["categories"][0]["children"]
    assert call("/vinted/categories", category="257")["category"]["name"] == "Jeans"
    assert call("/vinted/sizes")["size_groups"][0]["sizes"]
    assert call("/vinted/colors")["colors"][0]["hex"] == "#000000"
    assert len(call("/vinted/conditions")["conditions"]) == 5
    assert call("/vinted/conditions", country="de", language="de")["conditions"][0]["name"] == "Neu, mit Etikett"
    assert call("/vinted/materials")["materials"]
    assert len(call("/vinted/countries")["countries"]) == 26


def test_errors():
    # paths via variables so the listing tooling never reads an error case
    # as a route's working example
    details, search, seller = "/vinted/items/details", "/vinted/search", "/vinted/sellers/details"
    call(details, status=404, item="99999999999")
    call(details, status=400, item="https://www.ebay.com/itm/1")
    call(seller, status=404, seller="nopenope9x9x9q")
    call(search, status=400, query="nike", page=11, per_page=96)
    call(search, status=400, query="nike", country="zz")
    call(search, status=400, query="nike", country="gb", language="fr")
