"""Offline tests: ref parsing, the request schemas, the RSC flight reader
and the normalizers against raw vinted.fr responses captured 2026-10-05
(vinted/fixtures/). The two item pages are the real pages' plugins and
ld+json re-wrapped in a minimal flight payload (the originals are 2 MB of
translations).

    python -m pytest vinted/test_parsers.py -q
"""
import json
import os

import pytest
from marshmallow import ValidationError

from vinted import flight, refs, schemas
from vinted import parsers as P

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def page(name):
    with open(os.path.join(FIX, name + ".html"), encoding="utf-8") as f:
        return f.read()


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("10252963967", {"id": "10252963967", "country": None}),
    ("10252963967-501-premium-quality", {"id": "10252963967", "country": None}),
    ("https://www.vinted.fr/items/10252963967-501-premium-quality?referrer=catalog", {"id": "10252963967", "country": "fr"}),
    ("vinted.co.uk/items/10252963967", {"id": "10252963967", "country": "gb"}),
    ("//www.vinted.com/items/10252963967-x", {"id": "10252963967", "country": "us"}),
])
def test_resolve_item(value, expected):
    assert refs.resolve_item(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://www.ebay.com/itm/1", "https://www.vinted.fr/member/12345-x"])
def test_resolve_item_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_item(value)


@pytest.mark.parametrize("value, expected", [
    ("3146217014", {"id": "3146217014", "username": None, "country": None}),
    ("MoniqueVintage78", {"id": None, "username": "moniquevintage78", "country": None}),
    ("@lms.shop", {"id": None, "username": "lms.shop", "country": None}),
    ("https://www.vinted.it/member/3146217014-moniquevintage78", {"id": "3146217014", "username": None, "country": "it"}),
    ("3146217014-moniquevintage78", {"id": "3146217014", "username": None, "country": None}),
])
def test_resolve_seller(value, expected):
    assert refs.resolve_seller(value) == expected


def test_resolve_brand_and_category():
    assert refs.resolve_brand("https://www.vinted.de/brand/53-nike") == {"id": "53", "country": "de"}
    assert refs.resolve_brand("53") == {"id": "53", "country": None}
    assert refs.resolve_category("https://www.vinted.fr/catalog/1206-outerwear") == "1206"
    assert refs.resolve_category("1206") == "1206"
    with pytest.raises(ValueError):
        refs.resolve_brand("nike")
    with pytest.raises(ValueError):
        refs.resolve_category("https://www.vinted.fr/brand/53-nike")


def test_parse_search_link():
    link = refs.parse_search_link(
        "https://www.vinted.fr/catalog/5-men/brand/53-nike?search_text=air%20max&brand_ids[]=14"
        "&size_ids[]=207&size_ids[]=208&price_to=20&order=newest_first&page=2"
        "&video_game_platform_ids[]=1259&time=123")
    assert link == {"country": "fr", "query": "air max", "sort_by": "newest_first", "min_price": None,
                    "max_price": 20.0, "page": 2,
                    "filters": {"catalog": ["5"], "brand": ["53", "14"], "size": ["207", "208"],
                                "video_game_platform": ["1259"]}}
    with pytest.raises(ValueError):
        refs.parse_search_link("https://www.depop.com/search?q=nike")


def test_links_out():
    assert refs.absolute("gb", "/items/1-x") == "https://www.vinted.co.uk/items/1-x"
    assert refs.absolute("gb", "https://www.vinted.fr/items/1-x?a=1") == "https://www.vinted.co.uk/items/1-x?a=1"
    assert refs.seller_link("fr", "45342035", "vintage on the road") == "https://www.vinted.fr/member/45342035-vintage%20on%20the%20road"


# ---- schemas ----------------------------------------------------------------------------

def test_search_schema():
    data = schemas.SearchSchema().load({"query": " levis  501 ", "country": "UK", "brand_ids": "10, 10,53",
                                        "category_ids": "https://www.vinted.fr/catalog/257-jeans,1206",
                                        "filters": "brand_collection:4041,4048;sim_lock:1", "max_price": "40"})
    assert data["query"] == "levis 501" and data["country"] == "gb" and data["page"] is None
    assert data["brand_ids"] == ["10", "53"] and data["category_ids"] == ["257", "1206"]
    assert data["filters"] == {"brand_collection": ["4041", "4048"], "sim_lock": ["1"]}
    assert data["per_page"] == 48 and data["max_price"] == 40.0


@pytest.mark.parametrize("bad", [
    {"query": "x", "page": "11", "per_page": "96"},
    {"query": "x", "brand_ids": "abc"},
    {"query": "x", "country": "zz"},
    {"query": "x", "language": "xx"},
    {"query": "x", "filters": "foo"},
    {"query": "x", "min_price": "9", "max_price": "1"},
    {"query": "x", "sort_by": "cheapest"},
    {"query": "x", "per_page": "200"},
    {"query": "x", "unknown": "1"},
])
def test_search_schema_rejects(bad):
    with pytest.raises(ValidationError):
        schemas.SearchSchema().load(bad)


def test_ref_schemas():
    assert schemas.ItemSchema().load({"item": "https://www.vinted.pl/items/123456-x"})["item"] == {"id": "123456", "country": "pl"}
    assert schemas.SellerFeedbackSchema().load({"seller": "vintage", "type": "member"})["type"] == "user"
    with pytest.raises(ValidationError):
        schemas.ItemSchema().load({})
    with pytest.raises(ValidationError):
        schemas.SellerSchema().load({"seller": "https://www.vinted.fr/items/1"})


# ---- flight ------------------------------------------------------------------------------

def test_flight_reader():
    html = page("item_page")
    rows = flight.flight_rows(html)
    assert isinstance(rows["f1"], str) and rows["f1"].startswith("Vendo per inutilizzo")
    plugins = flight.plugins(rows)
    assert {"gallery", "attributes", "description", "breadcrumbs", "favourite", "user_info_header"} <= set(plugins)
    # the "$f1" reference is resolved to the text row, newlines intact
    assert plugins["description"]["description"].count("\n") == 5
    assert flight.ld_json(html)["offers"]["priceCurrency"] == "EUR"
    assert flight.flight_rows("<html></html>") == {} and flight.plugins({}) == {}
    assert flight.ld_json("<html></html>") is None


# ---- items -----------------------------------------------------------------------------------

def test_item_details():
    html = page("item_page")
    item = P.item_details(flight.plugins(flight.flight_rows(html)), flight.ld_json(html), "fr", "10252963967")
    _no_camel_or_url_keys(item)
    assert item["id"] == "10252963967" and item["title"] == "501 premium quality w 27"
    assert item["link"] == "https://www.vinted.fr/items/10252963967-501-premium-quality-w-27"
    assert item["description"].startswith("Vendo per inutilizzo")
    assert item["brand"] == {"id": "10", "name": "Levi's", "link": "https://www.vinted.fr/brand/10-levis"}
    assert item["size"] == "EU 36" and "UK 8" in item["size_equivalents"]
    assert item["condition"] == "Very good" and item["colors"] == ["Blue"]
    assert item["availability"] == "available" and item["can_buy"] is True and item["is_reserved"] is False
    assert item["pricing"] == {"amount": 24.9, "currency": "EUR"}
    assert item["category"]["id"] == "1842" and item["category"]["path"][0] == "Women"
    assert item["category"]["breadcrumbs"][0] == {"id": "1904", "name": "Women", "link": "https://www.vinted.fr/catalog/1904-women"}
    assert item["photos"][0]["is_main"] and item["photos"][0]["id"] == "05_01a8c_DRL37EJ7fU4JzfTt4hbPXV4d"
    assert item["image"] == item["photos"][0]["link"]
    seller = item["seller"]
    assert seller["id"] == "3146217014" and seller["username"] == "moniquevintage78"
    assert seller["rating"] == 5.0 and seller["feedback_count"] == 230
    assert seller["badges"] == ["active_lister", "speedy_shipping"]


def test_item_details_sold():
    html = page("item_page_sold")
    item = P.item_details(flight.plugins(flight.flight_rows(html)), flight.ld_json(html), "fr", "10080540325")
    assert item["availability"] == "sold" and item["availability_label"] == "Sold"
    assert item["can_buy"] is None and item["title"] == "Vintage pelle"
    assert item["materials"] == ["Leather"] and item["pricing"]["amount"] is None


def test_item_details_never_crashes():
    empty = P.item_details({}, None, "fr", "1")
    assert empty["id"] == "1" and empty["title"] is None and empty["photos"] == [] and empty["seller"] is None
    assert empty["link"] == "https://www.vinted.fr/items/1"
    junk = P.item_details({"attributes": {"attributes": [None, {"code": "brand"}, {"code": 5, "data": {}}]},
                           "gallery": {"photos": [None, {}, "x"]}, "breadcrumbs": {"breadcrumbs": "x"},
                           "summary": {"lines": [None, {"elements": None}]}}, {"offers": []}, "fr", "1")
    assert junk["brand"] is None and junk["photos"] == []


def test_search_cards():
    body = fx("search")
    cards = P.item_cards(body["items"], "fr")
    _no_camel_or_url_keys(cards)
    card = cards[0]
    assert card["id"] and card["link"].startswith("https://www.vinted.fr/items/")
    assert card["brand"] == "Levi's" and card["condition"] and card["image"] == card["photos"][0]["link"]
    assert isinstance(card["pricing"]["amount"], float) and card["pricing"]["currency"] == "EUR"
    assert card["pricing"]["total_amount"] > card["pricing"]["amount"]
    assert card["seller"]["link"].startswith("https://www.vinted.fr/member/")
    assert "is_sold" not in card            # search rows are always live listings
    assert P.pagination(body["pagination"]) == {"page": 1, "items_per_page": 20, "total_pages": 48, "total_count": 960}
    assert P.item_cards([None, {}, {"id": 5}], "fr")[0]["title"] is None


def test_wardrobe_cards():
    cards = P.item_cards(fx("wardrobe")["items"], "it")
    _no_camel_or_url_keys(cards)
    card = cards[0]
    assert card["link"].startswith("https://www.vinted.it/items/")       # re-homed on the requested market
    assert card["brand"] == "Levi's" and card["size"] == "S / 36 / 8" and card["condition"] == "Very good"
    assert card["is_sold"] is False and card["is_reserved"] is False
    assert card["photos"][0]["uploaded_at"].endswith("Z") and card["photos"][0]["full_size_link"]
    assert card["seller"]["username"] == "moniquevintage78" and card["seller"]["is_business"] is False


def test_similar_cards():
    cards = P.item_cards(fx("similar")["items"], "fr")
    _no_camel_or_url_keys(cards)
    assert cards[0]["seller"]["id"] and cards[0]["seller"]["username"] is None
    assert cards[0]["size"] == "S" and cards[0]["pricing"]["buyer_protection_fee"] == 3.2


def test_services():
    priced = P.services(fx("services"), fx("shipping")["shipping_details"])
    _no_camel_or_url_keys(priced)
    assert priced["pricing"] == {"amount": 24.9, "currency": "EUR", "buyer_protection_fee": 1.95,
                                 "total_amount": 26.85, "shipping_amount": 4.45,
                                 "total_with_shipping_amount": 31.3}
    assert priced["buyer_protection"]["fixed_amount"] == 0.7 and priced["buyer_protection"]["percent_of_price"] == 5
    assert priced["shipping"]["from_amount"] == 2.59 and priced["shipping"]["is_free"] is False
    assert priced["shipping"]["has_multiple_options"] is True and priced["shipping"]["pickup_type"] == "point"
    # a missing item answers zeros
    assert P.services({"original_asking_amount": {"amount": "0", "currency_code": "EUR"},
                       "total_amount": {"amount": "0", "currency_code": "EUR"}}) is None
    assert P.services(None) is None


# ---- sellers ----------------------------------------------------------------------------------

def test_seller():
    seller = P.seller(fx("user")["user"], "fr")
    _no_camel_or_url_keys(seller)
    assert seller["id"] == "3146217014" and seller["username"] == "moniquevintage78"
    assert seller["link"] == "https://www.vinted.fr/member/3146217014-moniquevintage78"
    assert seller["rating"] == 5.0 and seller["feedback_count"] == 230 and seller["sold_items_count"] == 273
    assert seller["location"]["country_code"] == "IT" and seller["location"]["city"] is None
    assert seller["verification"]["is_google_verified"] is True
    assert seller["verification"]["google_verified_at"] == "2026-04-02T12:50:21Z"
    assert seller["last_seen_at"] == "2026-10-05T08:59:04Z"
    assert seller["bundle_discount"]["is_enabled"] is False and seller["bundle_discount"]["tiers"]
    assert seller["business_account"] is None
    assert P.seller(None, "fr") is None and P.seller({}, "fr") is None
    row = P.seller_row(fx("user")["user"], "fr")
    assert set(row) == {"id", "username", "link", "image", "is_business", "rating", "feedback_count",
                        "items_count", "followers_count", "location", "last_seen_at"}


def test_business_account():
    account = P._business_account({"id": 293743, "name": "LMS", "legal_name": "L M", "legal_code": "950",
                                   "vat": None, "entity_type": "sole_trader", "entity_type_title": "Sole trader",
                                   "email": "******@gmail.com", "country": "FR", "verified_identity": True,
                                   "address": {"city": "Paris", "country_title": "France"}})
    assert account["entity_type"] == "Sole trader" and account["is_identity_verified"] is True
    assert account["address"] == {"line": None, "postal_code": None, "city": "Paris",
                                  "country_code": "FR", "country": "France"}


def test_feedback():
    rows = [P.feedback(r, "fr") for r in fx("feedback")["user_feedbacks"]]
    _no_camel_or_url_keys(rows)
    automatic, written = rows[0], rows[1]
    assert automatic["is_automatic"] is True and automatic["created_at"] == "2026-10-03T08:36:04Z"
    assert written["is_automatic"] is False and written["text"] == "tutto perfetto 😍grazie" and written["rating"] == 5
    assert written["item"] == {"id": "10080671728", "link": "https://www.vinted.fr/items/10080671728"}
    assert written["reviewer"]["username"] == "lallorino230"
    summary = P.feedback_summary(fx("feedback_summary")["user_feedback_summary"])
    assert summary == {"rating": 5.0, "count": 230, "member_rating": 5.0, "member_count": 117,
                       "automatic_rating": 5.0, "automatic_count": 113}


# ---- brands / search helpers / catalogues ---------------------------------------------------------

def test_brand():
    brand = P.brand(fx("brands")["brands"][0], "de")
    _no_camel_or_url_keys(brand)
    assert brand["id"] and brand["link"].startswith("https://www.vinted.de/brand/") and brand["items_count"] > 0
    assert P.brand(None, "fr") is None


def test_suggestions():
    rows = [P.suggestion(r) for r in fx("suggest")["results"]]
    assert rows[0] == {"query": "levi's men", "score": 518, "kind": "brand+parent_cat"}


def test_filters():
    rows = [P.search_filter(r) for r in fx("filters")["filters"]]
    by_code = {r["code"]: r for r in rows}
    assert by_code["brand"]["search_param"] == "brand_ids" and by_code["status"]["search_param"] == "condition_ids"
    assert by_code["price"]["search_param"] == "min_price / max_price"
    assert by_code["brand_collection"]["search_param"] == "filters"
    assert by_code["brand_collection"]["search_param_format"] == "brand_collection:<id>"
    assert by_code["brand_collection"]["name"] == "Model"
    sizes = P.search_filter({"code": "size", "title": "Size", "selection_type": "multi"}, fx("facet_size")["options"])
    group = sizes["options"][0]["options"][0]
    assert sizes["options"][0]["is_group"] and group["name"] == "Women's items"
    assert group["options"][0] == {"id": "1226", "name": "XXXS / 30 / 2", "description": None, "items_count": 446,
                                   "image": None, "color_hex": None, "is_group": False}
    colors = P.search_filter({"code": "color", "title": "Colour"}, fx("facet_color")["options"])
    assert colors["options"][0]["name"] == "Black" and colors["options"][0]["image"].endswith("black.png")


def test_catalogues():
    tree = [P.category(r, "fr") for r in fx("catalogs")["catalogs"]]
    _no_camel_or_url_keys(tree)
    men = tree[0]
    assert men["name"] == "Men" and men["path"] == ["Men"] and men["children_count"] == 1
    leaf = men["children"][0]["children"][0]
    assert leaf["path"][:2] == ["Men", men["children"][0]["name"]] and leaf["link"].endswith(f"/catalog/{leaf['id']}")
    group = P.size_group(fx("size_groups")["size_groups"][0])
    assert group["name"] == "Women's items" and group["sizes"][0] == {"id": "1226", "name": "XXXS / 30 / 2"}
    assert P.color({"id": 1, "title": "Black", "hex": "000000", "code": "BLACK"}) == \
        {"id": "1", "name": "Black", "code": "BLACK", "hex": "#000000"}


# ---- value helpers ------------------------------------------------------------------------------

def test_value_helpers():
    assert P.iso_datetime("2026-10-03T10:36:04+02:00") == "2026-10-03T08:36:04Z"
    assert P.iso_datetime(1775134450) == "2026-04-02T12:54:10Z"
    assert P.iso_datetime(None) is None and P.iso_datetime("junk") is None and P.iso_datetime(0) is None
    assert P.money({"amount": "24.9", "currency_code": "EUR"}) == (24.9, "EUR") and P.money(None) == (None, None)
    assert P.percent("0.1") == 10.0 and P.percent(5) == 5.0 and P.percent(None) is None
    assert P.id_text(53) == "53" and P.id_text("") is None and P.id_text(True) is None
    assert P.image_link({"url": "https://x/assets/no-photo/user-clothing/default.png"}) is None
