"""/vinted/items/* — one listing in full, the items the site shows as
similar, and its delivery + Buyer Protection pricing.

An item's own JSON route (/api/v2/items/<id>/details) is a block page for
an anonymous reader, so details are read from the item PAGE: its RSC
plugins (title, description, attributes, gallery, breadcrumbs, favourites,
availability, seller header + badges) and the ld+json Product. Three
enrichments run beside it and never fail the call: the pricing service
(Buyer Protection fee, total, delivery price), the delivery summary, and
the seller's public profile (rating, location, last seen).
"""
from vinted import flight
from vinted import parsers as P
from vinted.fetch import VintedNotFound, VintedUpstreamError, api, gateway, gather, get_page
from vinted.shared import market


def _pricing_parts(country, language, item_id):
    return {
        "services": lambda: gateway(country, f"/pricing/public/api/v1/items/{item_id}/services",
                                    language=language, label=f"item {item_id} pricing"),
        "shipping": lambda: api(country, f"/items/{item_id}/shipping_details",
                                language=language, label=f"item {item_id} shipping"),
    }


def _services(parts):
    shipping = parts.get("shipping") or {}
    return P.services(parts.get("services"), shipping.get("shipping_details") if isinstance(shipping, dict) else None)


def details(item, country=None, language=None):
    country, language = market(country, language, item.get("country"))
    item_id = item["id"]
    calls = _pricing_parts(country, language, item_id)
    calls["page"] = lambda: get_page(country, f"/items/{item_id}", language=language, label=f"item {item_id}")
    try:
        parts = gather(calls, optional=("services", "shipping"))
    except VintedNotFound:
        raise VintedNotFound(f"item '{item_id}' not found")

    html = parts["page"]
    plugins = flight.plugins(flight.flight_rows(html))
    ld = flight.ld_json(html)
    if not plugins and not ld:
        raise VintedUpstreamError(f"item {item_id} page carried no item data")
    out = P.item_details(plugins, ld, country, item_id)

    priced = _services(parts)
    if priced:
        # the pricing service is authoritative; the page price is the fallback
        pricing = priced["pricing"]
        if pricing["amount"] is None:
            pricing["amount"] = out["pricing"]["amount"]
        if pricing["currency"] is None:
            pricing["currency"] = out["pricing"]["currency"]
        out["pricing"] = pricing
        out["buyer_protection"] = priced["buyer_protection"]
        out["shipping"] = priced["shipping"]
    else:
        out["pricing"].update({"buyer_protection_fee": None, "total_amount": None,
                               "shipping_amount": None, "total_with_shipping_amount": None})
        out["buyer_protection"] = None
        out["shipping"] = None

    seller = out.get("seller")
    if seller and seller.get("id"):
        try:
            body = api(country, f"/users/{seller['id']}", language=language, label=f"seller {seller['id']}")
        except Exception:
            body = None
        profile = P.seller((body or {}).get("user"), country) if isinstance(body, dict) else None
        if profile:
            profile["badges"] = seller.get("badges") or []
            for key in ("rating", "feedback_count", "image", "username", "is_business"):
                if profile.get(key) is None:
                    profile[key] = seller.get(key)
            out["seller"] = profile
    return {"item": out}


def similar(item, country=None, language=None):
    """The "Similar items" block of an item page (up to 24)."""
    country, language = market(country, language, item.get("country"))
    item_id = item["id"]
    try:
        body = gateway(country, f"/item-details/more-items/{item_id}",
                       {"content_source": "similar_items", "screen": "item"},
                       language=language, label=f"item {item_id} similar items") or {}
    except VintedNotFound:
        raise VintedNotFound(f"item '{item_id}' not found")
    items = P.item_cards(body.get("items"), country)
    return {"item_id": item_id, "country": country.upper(), "count": len(items), "items": items}


def shipping(item, country=None, language=None):
    """Price breakdown for a buyer on this market: item price, Buyer
    Protection fee (and its rule), delivery price and the totals."""
    country, language = market(country, language, item.get("country"))
    item_id = item["id"]
    parts = gather(_pricing_parts(country, language, item_id), optional=("shipping",))
    priced = _services(parts)
    if not priced:
        raise VintedNotFound(f"item '{item_id}' not found")
    return dict({"item_id": item_id, "country": country.upper()}, **priced)
