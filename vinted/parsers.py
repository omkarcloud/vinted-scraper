"""Vinted normalizers: /api/v2 objects, /web/gateway objects and the item
page's plugins -> one clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical page URLs (always absolute, on the requested country site),
`image` for a picture link, `*_count` for counters, `is_*`/`has_*` for
booleans, ISO-8601 UTC ("2026-10-03T08:36:04Z") for timestamps, prices as a
numeric `amount` + a separate `currency`, null for missing. Entity refs
share one vocabulary:

  item card  {id, title, link, brand, size, condition, image,
              favourites_count, is_promoted, pricing{}, photos[], seller{}}
             (+ is_reserved / is_sold / is_hidden on wardrobe rows)
  seller     {id, username, link, image, is_business}
  photo      {id, link, full_size_link, width, height, dominant_color,
              is_main, uploaded_at}

Deliberately dropped as noise:
  * photo `thumbnails[]` (six signed resizes of the same picture; `link` is
    the 800 px one, `full_size_link` the original), `temp_uuid`, `extra`,
    `orientation`, `is_suspicious`, `image_no`, `dominant_color_opaque`
    (the pastel placeholder tint; the true `dominant_color` is kept)
  * `search_tracking_params`, `content_source`, `item_box.exposures` /
    `ff_exposures` / `accessibility_label` (a localized sentence repeating
    brand, size, condition and both prices), `uri` deep links (vintedfr://)
  * viewer-relative flags that are constant for an anonymous reader:
    `is_favourite`, `can_edit`, `can_push_up`, `can_change`, `can_delete`,
    `can_comment`, `hates_you`, `is_hated`, `follow_action_visible`,
    `stats_visible`, `transaction_permitted`, `allow_direct_messaging`
  * `view_count` (always 0 unless you own the item), `push_up`,
    `item_alert_type`, `item_closing_action`, `is_processing`
  * on users: `anon_id`, `email`, `real_name`, `birthday`, `contacts`,
    `default_address`, `facebook_user_id` (always null for other members),
    the moderator / catalog-role flags, `msg_template_count`,
    `third_party_tracking`, `is_publish_photos_agreed`, `fundraiser`,
    `account_status`, `country_id`, `city_id`, `updated_on`, `last_loged_on`
    (a localized "today 10:59"; the timestamp is kept as `last_seen_at`),
    `pretty_*` counters ("8.7M"; the exact numbers are kept)
  * on filters: `translations`, `search_translations`, `display_type`,
    `grid_columns`, `position`, `total_count_max`, option `prefix` sizes
"""
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from vinted import countries, refs

_PHOTO_ID_RE = re.compile(r"/t[c]?/([0-9]{2}_[0-9a-f]+_[A-Za-z0-9]+)/")
_DEFAULT_AVATAR_RE = re.compile(r"/assets/no-photo|default-avatar", re.I)


# ---- value helpers ------------------------------------------------------------
# (kept local so the package stands alone, like the other site packages)

def to_int(value):
    try:
        return int(value) if value not in (None, "") and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None      # NaN


def text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def id_text(value):
    """Ids are strings everywhere (Vinted mixes ints and strings)."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def iso_datetime(value):
    """'2026-10-03T10:36:04+02:00' or an epoch -> '2026-10-03T08:36:04Z'."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            if value <= 0:
                return None
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            raw = str(value).strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(value):
    """{"amount": "24.9", "currency_code": "EUR"} -> (24.9, "EUR")."""
    if not isinstance(value, dict):
        return None, None
    return to_float(value.get("amount")), text(value.get("currency_code") or value.get("currency"))


def amount(value):
    return money(value)[0]


def percent(value):
    """A 0-1 fraction ("0.1") or a percentage number -> a percentage number."""
    number = to_float(value)
    if number is None:
        return None
    if isinstance(value, str) and number <= 1:
        number *= 100
    return round(number, 2)


def pagination(raw, page=None, per_page=None):
    """Vinted's {current_page, total_pages, total_entries, per_page} -> the
    block route_glue.paginate lifts into the flat gateway shape."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "page": to_int(raw.get("current_page")) or page or 1,
        "items_per_page": to_int(raw.get("per_page")) or per_page,
        "total_pages": to_int(raw.get("total_pages")) or 0,
        "total_count": to_int(raw.get("total_entries")) or 0,
    }


# ---- photos ---------------------------------------------------------------------

def image_link(value):
    """A photo object or a bare URL -> one https link (None for the
    placeholder avatar)."""
    if isinstance(value, dict):
        value = value.get("url") or value.get("full_size_url")
    link = text(value)
    if not link or _DEFAULT_AVATAR_RE.search(link):
        return None
    return link


def photo(raw):
    if not isinstance(raw, dict):
        return None
    link = image_link(raw)
    if not link:
        return None
    high = raw.get("high_resolution") if isinstance(raw.get("high_resolution"), dict) else {}
    photo_id = text(high.get("id"))
    if not photo_id:
        match = _PHOTO_ID_RE.search(link)
        photo_id = match.group(1) if match else None
    return {
        "id": photo_id,
        "link": link,
        "full_size_link": text(raw.get("full_size_url")),
        "width": to_int(raw.get("width")) or None,
        "height": to_int(raw.get("height")) or None,
        "dominant_color": text(raw.get("dominant_color")),
        "is_main": bool(raw.get("is_main")),
        "uploaded_at": iso_datetime(high.get("timestamp")),
    }


def photos(raw_list, fallback=None):
    out = [p for p in (photo(r) for r in (raw_list if isinstance(raw_list, list) else [])) if p]
    if not out and fallback is not None:
        one = photo(fallback)
        if one:
            out = [one]
    out.sort(key=lambda p: not p["is_main"])      # main first, order otherwise kept
    return out


# ---- sellers --------------------------------------------------------------------

def seller_ref(raw, country, seller_id=None):
    """The small seller object embedded in cards, feedback and lists."""
    raw = raw if isinstance(raw, dict) else {}
    sid = id_text(raw.get("id")) or id_text(seller_id)
    if not sid:
        return None
    username = text(raw.get("login"))
    business = raw.get("business")
    if business is None:
        business = raw.get("is_business")
    return {
        "id": sid,
        "username": username,
        "link": refs.seller_link(country, sid, username),
        "image": image_link(raw.get("photo")),
        "is_business": bool_or_none(business),
    }


def _verification(raw):
    raw = raw if isinstance(raw, dict) else {}

    def valid(key):
        node = raw.get(key)
        return bool(node.get("valid")) if isinstance(node, dict) else None

    google = raw.get("google") if isinstance(raw.get("google"), dict) else {}
    facebook = raw.get("facebook") if isinstance(raw.get("facebook"), dict) else {}
    return {
        "is_email_verified": valid("email"),
        "is_google_verified": valid("google"),
        "is_facebook_verified": valid("facebook"),
        "is_phone_verified": valid("phone"),
        "google_verified_at": iso_datetime(google.get("verified_at")),
        "facebook_verified_at": iso_datetime(facebook.get("verified_at")),
    }


def _bundle_discount(raw):
    if not isinstance(raw, dict):
        return None
    tiers = []
    for row in raw.get("discounts") if isinstance(raw.get("discounts"), list) else []:
        if isinstance(row, dict) and percent(row.get("fraction")):
            tiers.append({"min_items": to_int(row.get("minimal_item_count")),
                          "discount_percent": percent(row.get("fraction"))})
    return {"is_enabled": bool(raw.get("enabled")), "tiers": tiers}


def _business_account(raw):
    """A professional seller's legal identity (Vinted itself masks the
    e-mail and phone: "******@gmail.com", "+33*********")."""
    if not isinstance(raw, dict):
        return None
    address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    return {
        "id": id_text(raw.get("id")),
        "name": text(raw.get("name")),
        "legal_name": text(raw.get("legal_name")),
        "legal_code": text(raw.get("legal_code")),
        "registrar_name": text(raw.get("registrar_name")),
        "vat_number": text(raw.get("vat")),
        "entity_type": text(raw.get("entity_type_title")) or text(raw.get("entity_type")),
        "email": text(raw.get("email")),
        "phone_number": text(raw.get("phone_number")),
        "is_identity_verified": bool_or_none(raw.get("verified_identity")),
        "is_active": bool_or_none(raw.get("is_active")),
        "address": {
            "line": text(address.get("line1")) or text(address.get("address")),
            "postal_code": text(address.get("postal_code")),
            "city": text(address.get("city")),
            "country_code": text(raw.get("country")),
            "country": text(address.get("country_title")) or text(raw.get("country_title")),
        },
    }


def seller(raw, country):
    """The full /api/v2/users/<id> object."""
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    sid = id_text(raw.get("id"))
    username = text(raw.get("login"))
    reputation = to_float(raw.get("feedback_reputation"))
    feedback_count = to_int(raw.get("feedback_count"))
    business = raw.get("business")
    if business is None:
        business = raw.get("is_business")
    return {
        "id": sid,
        "username": username,
        "link": refs.seller_link(country, sid, username),
        "image": image_link(raw.get("photo")),
        "about": text(raw.get("about")),
        "is_business": bool_or_none(business),
        # 0-1 share of positive feedback, as a 0-5 star rating (what the site shows)
        "rating": round(reputation * 5, 2) if reputation is not None and feedback_count else None,
        "feedback_count": feedback_count,
        "positive_feedback_count": to_int(raw.get("positive_feedback_count")),
        "neutral_feedback_count": to_int(raw.get("neutral_feedback_count")),
        "negative_feedback_count": to_int(raw.get("negative_feedback_count")),
        "items_count": to_int(raw.get("item_count")),
        "total_items_count": to_int(raw.get("total_items_count")),
        "sold_items_count": to_int(raw.get("given_item_count")),
        "bought_items_count": to_int(raw.get("taken_item_count")),
        "followers_count": to_int(raw.get("followers_count")),
        "following_count": to_int(raw.get("following_count")),
        "following_brands_count": to_int(raw.get("following_brands_count")),
        "is_online": bool_or_none(raw.get("is_online")),
        "is_on_holiday": bool_or_none(raw.get("is_on_holiday")),
        "is_banned": bool_or_none(raw.get("is_account_banned")),
        "is_deleted": bool_or_none(raw.get("is_deleted")),
        "has_hidden_feedback": bool_or_none(raw.get("hide_feedback")),
        "can_bundle": bool_or_none(raw.get("can_bundle")),
        "average_response_time": text(raw.get("avg_response_time")) if isinstance(raw.get("avg_response_time"), str) else to_int(raw.get("avg_response_time")),
        "location": {
            "city": text(raw.get("city")),
            "country_code": text(raw.get("country_iso_code") or raw.get("country_code")),
            "country": text(raw.get("country_title")),
            "description": text(raw.get("location_description")),
        },
        "verification": _verification(raw.get("verification")),
        "bundle_discount": _bundle_discount(raw.get("bundle_discount")),
        "business_account": _business_account(raw.get("business_account")),
        "currency": text(raw.get("currency")),
        "locale": text(raw.get("iso_locale_code")),
        "last_seen_at": iso_datetime(raw.get("last_loged_on_ts")),
        "banned_at": iso_datetime(raw.get("account_ban_date")),
    }


def seller_row(raw, country):
    """A member in a followers / following / search list (a lighter user
    object: counts and location are not always present)."""
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    full = seller(raw, country)
    keep = ("id", "username", "link", "image", "is_business", "rating", "feedback_count",
            "items_count", "followers_count", "location", "last_seen_at")
    row = {key: full[key] for key in keep}
    row["location"] = {k: full["location"][k] for k in ("city", "country_code", "country")}
    return row


# ---- item cards -------------------------------------------------------------------

def _pricing(raw):
    price, currency = money(raw.get("price"))
    if currency is None:
        currency = text(raw.get("currency"))
    fee = amount(raw.get("service_fee"))
    total = amount(raw.get("total_item_price"))
    return {
        "amount": price,
        "currency": currency,
        "buyer_protection_fee": fee,
        "total_amount": total,
    }


def _box_lines(raw):
    """item_box -> (brand, size, condition). first_line is the brand,
    second_line is 'S · Very good' or just 'Very good'."""
    box = raw.get("item_box") if isinstance(raw.get("item_box"), dict) else {}
    brand = text(box.get("first_line"))
    second = text(box.get("second_line"))
    size = condition = None
    if second:
        parts = [p.strip() for p in second.split(" · ") if p.strip()]
        if len(parts) >= 2:
            size, condition = " · ".join(parts[:-1]), parts[-1]
        elif parts:
            condition = parts[0]
    return brand, size, condition


def item_card(raw, country, seller_override=None):
    """One item of a search page, a wardrobe or a similar-items block."""
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    item_id = id_text(raw.get("id"))
    box_brand, box_size, box_condition = _box_lines(raw)
    pictures = photos(raw.get("photos"), fallback=raw.get("photo"))
    path = raw.get("url") or raw.get("path")
    seller_obj = seller_override or seller_ref(raw.get("user"), country, seller_id=raw.get("user_id"))
    if seller_obj and seller_obj.get("is_business") is None:
        flag = raw.get("business_user")
        if flag is None:
            flag = raw.get("is_business_user")
        seller_obj = dict(seller_obj, is_business=bool_or_none(flag))
    card = {
        "id": item_id,
        "title": text(raw.get("title")),
        "link": refs.absolute(country, path) or refs.item_link(country, item_id),
        "brand": text(raw.get("brand")) if isinstance(raw.get("brand"), str) else box_brand,
        "size": text(raw.get("size")) if isinstance(raw.get("size"), str) else box_size,
        "condition": text(raw.get("status")) if isinstance(raw.get("status"), str) else box_condition,
        "image": pictures[0]["link"] if pictures else None,
        "favourites_count": to_int(raw.get("favourite_count")),
        "is_promoted": bool_or_none(raw.get("promoted")),
        "pricing": _pricing(raw),
        "photos": pictures,
        "seller": seller_obj,
    }
    if "is_reserved" in raw or "is_closed" in raw:
        # wardrobe rows only: search and similar-items rows are always live listings
        card["is_reserved"] = bool_or_none(raw.get("is_reserved"))
        card["is_sold"] = bool_or_none(raw.get("is_closed"))
        card["is_hidden"] = bool_or_none(raw.get("is_hidden"))
    return card


def item_cards(rows, country, seller_override=None):
    out = []
    for row in rows if isinstance(rows, list) else []:
        card = item_card(row, country, seller_override)
        if card:
            out.append(card)
    return out


# ---- item details -------------------------------------------------------------------

# attribute codes lifted to top-level fields; the rest go to other_attributes
_LIFTED = {"brand", "size", "size_familiar", "status", "color", "material", "upload_date"}


def _size_equivalents(attr_data):
    """The size attribute links to a size guide whose query lists the
    listed size and its equivalents (EU 36 -> S, FR 38, IT 40, UK 8 ...)."""
    link = attr_data.get("url") or attr_data.get("uri")
    if not isinstance(link, str) or "equivalent_sizes" not in link:
        return []
    query = parse_qs(urlparse(link).query)
    out = []
    for value in query.get("equivalent_sizes", []):
        value = value.strip()
        if value and value not in out:
            out.append(value)
    return out


def _split_values(value):
    return [part.strip() for part in value.split(",") if part.strip()] if value else []


def _breadcrumbs(data, country):
    rows = []
    for crumb in data.get("breadcrumbs") if isinstance(data.get("breadcrumbs"), list) else []:
        if not isinstance(crumb, dict):
            continue
        link = text(crumb.get("url"))
        match = re.search(r"/catalog/(\d+)", link or "")
        brand_match = re.search(r"/brand/(\d+)", link or "")
        if not match:
            continue                     # the trailing "<Brand> <category>" crumb is a brand shortcut
        if brand_match:
            continue
        rows.append({"id": match.group(1), "name": text(crumb.get("title")),
                     "link": refs.absolute(country, link)})
    return rows


def item_details(plugins, ld, country, item_id):
    """The item page's plugins (+ ld+json Product) -> the item object.
    Pricing and the seller profile are enriched by the caller."""
    plugins = plugins if isinstance(plugins, dict) else {}
    ld = ld if isinstance(ld, dict) else {}

    def plug(name):
        value = plugins.get(name)
        return value if isinstance(value, dict) else {}

    attrs = {}
    other = []
    for attr in plug("attributes").get("attributes") if isinstance(plug("attributes").get("attributes"), list) else []:
        if not isinstance(attr, dict) or not isinstance(attr.get("data"), dict):
            continue
        code = text(attr.get("code"))
        if not code:
            continue
        attrs[code] = attr["data"]
        if code not in _LIFTED:
            other.append({"code": code, "name": text(attr["data"].get("title")),
                          "value": text(attr["data"].get("value")) if isinstance(attr["data"].get("value"), str)
                          else attr["data"].get("value")})

    def attr_value(*codes):
        for code in codes:
            value = attrs.get(code, {}).get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    brand_data = attrs.get("brand", {})
    brand_id = id_text(brand_data.get("id")) or id_text(plug("breadcrumbs").get("brand_id"))
    brand_name = attr_value("brand") or text((ld.get("brand") or {}).get("name") if isinstance(ld.get("brand"), dict) else None)
    brand_path = text(brand_data.get("url"))
    size_data = attrs.get("size_familiar") or attrs.get("size") or {}

    offer_data = plug("make_offer")
    gallery = plug("gallery")
    pictures = photos(gallery.get("photos")) or photos(offer_data.get("photos"))
    title = (text(gallery.get("accessibility_label")) or text(offer_data.get("title")) or text(ld.get("name")))
    if not title:
        for line in plug("summary").get("lines") if isinstance(plug("summary").get("lines"), list) else []:
            for element in line.get("elements") if isinstance(line, dict) and isinstance(line.get("elements"), list) else []:
                if isinstance(element, dict) and element.get("style") == "title":
                    title = text(element.get("value"))
                    break
            if title:
                break

    description = plug("description").get("description")
    description = text(description) if isinstance(description, str) and not description.startswith("$") else None
    if description is None:
        description = text(ld.get("description"))

    crumbs = _breadcrumbs(plug("breadcrumbs"), country)
    category_id = id_text(plug("breadcrumbs").get("catalog_id")) or (crumbs[-1]["id"] if crumbs else None)
    category_name = next((c["name"] for c in crumbs if c["id"] == category_id), None) or (crumbs[-1]["name"] if crumbs else None)

    ask = plug("ask_seller")
    status = plug("buyer_item_status")
    offer = ld.get("offers") if isinstance(ld.get("offers"), dict) else {}
    price, currency = money(offer_data.get("price"))
    if price is None:
        price, currency = to_float(offer.get("price")), text(offer.get("priceCurrency"))

    is_sold = bool(status) and not ask and not plug("buy")
    is_reserved = bool_or_none(ask.get("is_reserved"))
    is_hidden = bool_or_none(ask.get("is_hidden"))
    can_buy = bool_or_none(ask.get("can_buy"))
    if is_sold:
        availability = "sold"
    elif is_reserved:
        availability = "reserved"
    elif is_hidden:
        availability = "hidden"
    elif can_buy or offer.get("availability") == "InStock":
        availability = "available"
    else:
        availability = "unavailable" if ask else None

    header = plug("user_info_header")
    seller_id = (id_text(header.get("seller_id")) or id_text(gallery.get("seller_id"))
                 or id_text(ask.get("seller_id")) or id_text(plug("favourite").get("seller_id")))
    reputation = to_float(header.get("feedback_reputation"))
    feedback_count = to_int(header.get("feedback_count"))
    badges = []
    for badge in plug("seller_badges_info").get("badges") if isinstance(plug("seller_badges_info").get("badges"), list) else []:
        if isinstance(badge, dict) and text(badge.get("type")):
            badges.append(badge["type"].strip().lower())
    username = text(header.get("name")) or text(plug("seller_badges_info").get("username"))
    seller_obj = None
    if seller_id:
        seller_obj = {
            "id": seller_id,
            "username": username,
            "link": refs.seller_link(country, seller_id, username),
            "image": image_link(header.get("photo")),
            "is_business": bool_or_none(header.get("business")),
            "rating": round(reputation * 5, 2) if reputation is not None and feedback_count else None,
            "feedback_count": feedback_count,
            "badges": badges,
        }

    return {
        "id": id_text(item_id),
        "title": title,
        "link": text(offer.get("url")) and refs.absolute(country, offer.get("url")) or refs.item_link(country, item_id),
        "description": description,
        "brand": {"id": brand_id, "name": brand_name,
                  "link": refs.absolute(country, brand_path) if brand_path else refs.brand_link(country, brand_id)}
                 if (brand_id or brand_name) else None,
        "size": attr_value("size_familiar", "size"),
        "size_equivalents": _size_equivalents(size_data),
        "condition": attr_value("status"),
        "colors": _split_values(attr_value("color")) or _split_values(text(ld.get("color"))),
        "materials": _split_values(attr_value("material")),
        "other_attributes": other,
        "image": pictures[0]["link"] if pictures else text(ld.get("image")),
        "availability": availability,
        "availability_label": text(status.get("title")),
        "is_reserved": is_reserved,
        "is_hidden": is_hidden,
        "can_buy": can_buy,
        "has_instant_buy": bool_or_none(ask.get("instant_buy")),
        "favourites_count": to_int(plug("favourite").get("favourite_count")),
        "uploaded_ago": attr_value("upload_date"),
        "pricing": {"amount": price, "currency": currency},
        "category": {"id": category_id, "name": category_name,
                     "link": refs.category_link(country, category_id),
                     "path": [c["name"] for c in crumbs if c["name"]],
                     "breadcrumbs": crumbs} if (category_id or crumbs) else None,
        "photos": pictures,
        "seller": seller_obj,
    }


# ---- pricing / shipping ---------------------------------------------------------------

def _discounted(node):
    """A {original_price, final_price, discount, discount_percentage,
    lowest_price_30_days} block -> flat numbers."""
    node = node if isinstance(node, dict) else {}
    return {
        "amount": amount(node.get("final_price")),
        "original_amount": amount(node.get("original_price")),
        "discount_amount": amount(node.get("discount")),
        "discount_percent": to_float(node.get("discount_percentage")),
        "lowest_amount_30_days": amount(node.get("lowest_price_30_days")),
    }


def services(raw, shipping_details=None):
    """pricing .../items/<id>/services (+ /items/<id>/shipping_details) ->
    {"pricing", "buyer_protection", "shipping"}; None when the item does
    not exist (the service answers zeros)."""
    if not isinstance(raw, dict):
        return None
    price, currency = money(raw.get("original_asking_amount"))
    total = amount(raw.get("total_amount"))
    if not price and not total:
        return None
    blocks = raw.get("services") if isinstance(raw.get("services"), dict) else {}
    protection_raw = blocks.get("buyer_protection") if isinstance(blocks.get("buyer_protection"), dict) else None
    shipping_raw = blocks.get("shipping") if isinstance(blocks.get("shipping"), dict) else None
    details = shipping_details if isinstance(shipping_details, dict) else {}

    protection = None
    if protection_raw:
        rule = protection_raw.get("pricing_rule") if isinstance(protection_raw.get("pricing_rule"), dict) else {}
        protection = dict(_discounted(protection_raw),
                          fixed_amount=amount(rule.get("fixed_part")),
                          percent_of_price=to_float(rule.get("offer_price_percentage")))

    shipping = None
    if shipping_raw or details:
        shipping_raw = shipping_raw or {}
        rule = shipping_raw.get("pricing_rule") if isinstance(shipping_raw.get("pricing_rule"), dict) else {}
        info = rule.get("additional_info") if isinstance(rule.get("additional_info"), dict) else {}
        discount_rule = shipping_raw.get("discount_rule") if isinstance(shipping_raw.get("discount_rule"), dict) else {}
        pickup_only = shipping_raw.get("pickup_only")
        if pickup_only is None:
            pickup_only = details.get("pickup_only", raw.get("services", {}).get("pickup_only") if isinstance(raw.get("services"), dict) else None)
        multiple = info.get("multiple_shipping_options_available")
        if multiple is None:
            multiple = details.get("multiple_shipping_options_available")
        flat = _discounted(shipping_raw)
        if flat["amount"] is None:
            flat["amount"] = amount(details.get("price"))
        shipping = dict(
            flat,
            is_free=bool_or_none(details.get("free_shipping")) if details else (flat["amount"] == 0 if flat["amount"] is not None else None),
            is_pickup_only=bool_or_none(pickup_only),
            has_multiple_options=bool_or_none(multiple),
            from_amount=amount(details.get("price")),
            pickup_type=text(info.get("pickup_type") or discount_rule.get("pickup_type")),
            seller_discount_amount=amount(shipping_raw.get("seller_discount")),
            discount_ends_at=iso_datetime(discount_rule.get("end_date")) if to_float(discount_rule.get("percentage")) else None,
        )

    fee = protection["amount"] if protection else None
    ship = shipping["amount"] if shipping else None
    return {
        "pricing": {
            "amount": price,
            "currency": currency,
            "buyer_protection_fee": fee,
            "total_amount": total,
            "shipping_amount": ship,
            "total_with_shipping_amount": round(total + ship, 2) if total is not None and ship is not None else None,
        },
        "buyer_protection": protection,
        "shipping": shipping,
    }


# ---- feedback -------------------------------------------------------------------------

def feedback(raw, country):
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    reply = raw.get("comment") if isinstance(raw.get("comment"), dict) else {}
    item_id = id_text(raw.get("item_id"))
    return {
        "id": id_text(raw.get("id")),
        "rating": to_int(raw.get("rating")),
        "text": text(raw.get("feedback")),
        "is_automatic": bool(raw.get("system_feedback")),
        "reply": text(reply.get("comment")),
        "created_at": iso_datetime(raw.get("created_at_ts")),
        "item": {"id": item_id, "link": refs.item_link(country, item_id)} if item_id else None,
        "reviewer": seller_ref(raw.get("user"), country, seller_id=raw.get("feedback_user_id")),
    }


def feedback_summary(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "rating": to_float(raw.get("feedback_rating")),
        "count": to_int(raw.get("feedback_count")),
        "member_rating": to_float(raw.get("user_feedback_rating")),
        "member_count": to_int(raw.get("user_feedback_count")),
        "automatic_rating": to_float(raw.get("system_feedback_rating")),
        "automatic_count": to_int(raw.get("system_feedback_count")),
    }


# ---- brands ---------------------------------------------------------------------------

def brand(raw, country):
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    brand_id = id_text(raw.get("id"))
    slug = text(raw.get("slug"))
    return {
        "id": brand_id,
        "name": text(raw.get("title")),
        "slug": slug,
        "link": refs.absolute(country, raw.get("path")) or refs.brand_link(country, brand_id, slug),
        "items_count": to_int(raw.get("item_count")),
        "favourites_count": to_int(raw.get("favourite_count")),
        "is_luxury": bool_or_none(raw.get("is_luxury")),
        "requires_authenticity_check": bool_or_none(raw.get("requires_authenticity_check")),
        "is_visible_in_listings": bool_or_none(raw.get("is_visible_in_listings")),
    }


# ---- search helpers -----------------------------------------------------------------------

def suggestion(raw):
    if not isinstance(raw, dict) or not text(raw.get("title")):
        return None
    entries = raw.get("params_entries") if isinstance(raw.get("params_entries"), dict) else {}

    def first(key):
        value = entries.get(key)
        return value[0] if isinstance(value, list) and value else None

    return {"query": text(raw.get("title")), "score": to_int(first("total_score")),
            "kind": text(first("entity_combination"))}


# gateway filter code -> the /vinted/search param that takes its option ids
FILTER_PARAMS = {"catalog": "category_ids", "brand": "brand_ids", "size": "size_ids",
                 "status": "condition_ids", "color": "color_ids", "material": "material_ids",
                 "patterns": "pattern_ids"}


def filter_option(raw):
    """One facet option; groups (size families, navigational category
    levels) nest their children under `options`."""
    if not isinstance(raw, dict):
        return None
    prefix = raw.get("prefix") if isinstance(raw.get("prefix"), dict) else {}
    hex_code = text(prefix.get("hex"))
    children = [o for o in (filter_option(c) for c in (raw.get("options") if isinstance(raw.get("options"), list) else [])) if o]
    kind = text(raw.get("type"))
    out = {
        "id": id_text(raw.get("id")),
        "name": text(raw.get("title")),
        "description": text(raw.get("description")),
        "items_count": to_int(raw.get("items_count")),
        "image": text(prefix.get("url")),
        "color_hex": f"#{hex_code.lstrip('#')}" if hex_code else None,
        "is_group": kind in ("group", "navigational") or bool(children),
    }
    if children or out["is_group"]:
        out["options"] = children
    return out


def search_filter(raw, options=None):
    if not isinstance(raw, dict) or not text(raw.get("code")):
        return None
    code = raw["code"].strip()
    rows = options if options is not None else raw.get("options")
    parsed = [o for o in (filter_option(r) for r in (rows if isinstance(rows, list) else [])) if o]
    if code == "price":
        param, usage = "min_price / max_price", None
    elif code in FILTER_PARAMS:
        param, usage = FILTER_PARAMS[code], None
    else:
        param, usage = "filters", f"{code}:<id>"
    return {
        "code": code,
        "name": text(raw.get("title")),
        "search_param": param,
        "search_param_format": usage,
        "is_multi_select": raw.get("selection_type") == "multi",
        "options": parsed,
    }


def faceted_category(raw, country):
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    category_id = id_text(raw.get("id"))
    return {
        "id": category_id,
        "name": text(raw.get("title")),
        "link": refs.category_link(country, category_id),
        "image": image_link(raw.get("photo")),
        "items_count": to_int(raw.get("item_count")),
    }


# ---- reference catalogues ---------------------------------------------------------------------

def category(raw, country, parents=()):
    """One node of the /item_upload/catalogs tree (recursive)."""
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    category_id = id_text(raw.get("id"))
    name = text(raw.get("title"))
    path = list(parents) + ([name] if name else [])
    children = [c for c in (category(child, country, path) for child in
                            (raw.get("catalogs") if isinstance(raw.get("catalogs"), list) else [])) if c]
    return {
        "id": category_id,
        "name": name,
        "link": refs.category_link(country, category_id),
        "path": path,
        "image": image_link(raw.get("photo")),
        "children_count": len(children),
        "children": children,
    }


def color(raw):
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    hex_code = text(raw.get("hex"))
    return {"id": id_text(raw.get("id")), "name": text(raw.get("title")),
            "code": text(raw.get("code")), "hex": f"#{hex_code.lstrip('#')}" if hex_code else None}


def size_group(raw):
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    sizes = []
    for row in raw.get("sizes") if isinstance(raw.get("sizes"), list) else []:
        if isinstance(row, dict) and row.get("id") is not None:
            sizes.append({"id": id_text(row.get("id")), "name": text(row.get("title"))})
    return {"id": id_text(raw.get("id")), "name": text(raw.get("description")),
            "label": text(raw.get("caption")), "sizes": sizes}


def simple_option(raw):
    """A flat reference row built from a facet option (condition, material)."""
    option = filter_option(raw)
    if not option or not option["id"]:
        return None
    return {"id": option["id"], "name": option["name"], "description": option["description"]}
