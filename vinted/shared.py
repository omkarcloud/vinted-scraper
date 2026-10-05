"""Lookups shared by the /vinted/* endpoint modules: the effective market
of a request, seller reference -> numeric id + home market, and a small
in-process memo for values that never (ids) or rarely (catalogues) change."""
import threading
import time

from vinted import countries
from vinted import parsers as P
from vinted.fetch import VintedNotFound, api

ID_TTL = 24 * 3600
TABLE_TTL = 6 * 3600

_lock = threading.Lock()
_memo = {}


def memo(key, ttl, build):
    now = time.time()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        _memo[key] = (now + ttl, value)
    return value


def remember(key, ttl, value):
    with _lock:
        _memo[key] = (time.time() + ttl, value)


def recall(key):
    with _lock:
        hit = _memo.get(key)
        return hit[1] if hit and hit[0] > time.time() else None


def market(country=None, language=None, ref_country=None):
    """The (country, language) a request runs on: the explicit `country`
    param, else the country site of the link that was passed, else France
    (Vinted's largest market). The language must be one the site serves."""
    code = country or ref_country or countries.DEFAULT_COUNTRY
    language = language or countries.DEFAULT_LANGUAGE
    if language not in countries.languages(code):
        raise ValueError(f"language '{language}' is not available on Vinted {countries.name(code)} — "
                         f"one of: {', '.join(countries.languages(code))}")
    return code, language


def seller_raw(ref, country, language=None):
    """The /api/v2/users object for a resolved seller reference (id or
    username). Seeds the username -> id and id -> home country memos."""
    key = ref.get("id") or ref.get("username")
    try:
        body = api(country, f"/users/{key}", language=language, label=f"seller '{key}'")
    except VintedNotFound:
        raise VintedNotFound(f"seller '{key}' not found")
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, dict) or user.get("id") is None:
        raise VintedNotFound(f"seller '{key}' not found")
    seller_id = P.id_text(user.get("id"))
    username = P.text(user.get("login"))
    if username:
        remember(("seller_id", username.lower()), ID_TTL, seller_id)
    home = countries.normalize(user.get("country_iso_code") or user.get("country_code"))
    remember(("seller_home", seller_id), ID_TTL, home)
    return user


def seller_id(ref, country):
    """Resolved seller reference -> the numeric member id (a username costs
    one profile call, memoised for a day)."""
    if ref.get("id"):
        return ref["id"]
    known = recall(("seller_id", ref["username"]))
    if known:
        return known
    return P.id_text(seller_raw(ref, country)["id"])


def seller_market(ref, country=None, language=None):
    """The market a seller's wardrobe / feedback is read on. A wardrobe is
    only listed in full on the seller's own market (a French seller's
    wardrobe is empty on vinted.co.uk), so without an explicit `country`
    or a profile link the seller's home country is looked up."""
    if country or ref.get("country"):
        return market(country, language, ref.get("country"))
    sid = ref.get("id") or recall(("seller_id", ref.get("username") or ""))
    home = recall(("seller_home", sid)) if sid else None
    if home is None:
        user = seller_raw(ref, countries.DEFAULT_COUNTRY)
        home = countries.normalize(user.get("country_iso_code") or user.get("country_code"))
    return market(home, language)
