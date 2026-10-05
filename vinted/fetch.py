"""Vinted transport: plain curl_cffi with browser-impersonated TLS. No
browser (validated 2026-10-05 from direct Indian egress on all 26 country
sites; a 25-search burst from one IP all 200).

Auth: every JSON surface wants the anonymous `access_token_web` JWT the site
sets as a cookie on ANY page load — a 404 page (18 KB) is enough. The token
lives 24 h, is not bound to the host or the session that minted it, and is
accepted as `Authorization: Bearer` on every country host. One token is
kept process-wide and re-minted every config.VINTED_TOKEN_MAX_AGE seconds
or on the first 401 / gateway FORBIDDEN.

Market + language: the `Locale` header (`<language>-<COUNTRY>`, e.g. en-FR,
pl-PL). Without it the gateway answers for the French market in French on
every host — which is why a naive client sees EUR prices on vinted.co.uk.
The /api/v2 routes scope by HOST (a wardrobe is listed on the seller's own
market host) and translate by the same header; pages translate by the
`anonymous-iso-locale` cookie.

Three upstream surfaces per country host (vinted/countries.py):

  * API      https://<host>/api/v2/...
    users/<id|login>, users?search_text=, wardrobe/<id>/items,
    user_feedbacks, users/<id>/followers|followed_users, brands, brands/<id>,
    items/<id>/shipping_details, item_upload/catalogs (the category tree),
    size_groups, colors, countries. The old catalog/items, catalog/filters,
    catalogs and items/<id> routes are gone (404); items/<id>/details is a
    403 block page for an anonymous reader.

  * GATEWAY  https://<host>/web/gateway/...
    svc-catalogue/items (search; hard cap 960 results), svc-filters/filters,
    svc-filters/filters/facets, svc-filters/faceted_categories,
    search-bar/v2/suggestions, item-details/more-items/<id> (similar items;
    500s without the Locale header), pricing/public/api/v1/items/<id>/services.

  * PAGE     https://<host>/items/<id>
    The item page: an RSC flight payload of "plugins" (vinted/flight.py) and
    a ld+json Product. The only anonymous source of an item's description,
    attributes, full gallery and breadcrumbs.

Blocks: Cloudflare is in front without a challenge for Chrome TLS. A
403/429 that is NOT one of Vinted's own JSON errors is a block: the worker
moves its session to a sticky residential exit
(config.vinted_fallback_proxy()) for config.VINTED_BLOCK_COOLDOWN seconds —
the same shape as the kick / soundcloud transports.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  VintedUpstreamError  transport failure / 5xx              — retryable
  VintedBlocked        403 / 429 block page, token refused  — retryable on a new exit / token
  VintedBadRequest     upstream 400 / 422                    — never retried
  VintedNotFound       404 / missing entity                  — never retried
"""
import base64
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from vinted import countries

IMPERSONATE = "chrome"
API = "/api/v2"
GATEWAY = "/web/gateway"
TOKEN_COOKIE = "access_token_web"
# Any path that 404s sets the token cookie on an 18 KB body (the homepage is 2 MB).
TOKEN_PATHS = ("/page-not-found", "/")

TIMEOUT = 40
PAGE_TIMEOUT = 60
FANOUT_WORKERS = 12

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}


class VintedUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class VintedBlocked(VintedUpstreamError, Blocked):
    """403 / 429 block page, or the anonymous token was refused — retryable."""


class VintedBadRequest(BadRequest):
    """Upstream 400 / 422 — the params were rejected. Never retried."""


class VintedNotFound(NotFound):
    """Entity / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's sessions go through a sticky residential exit for a cooldown.
# Sessions carry no state: auth is the Bearer header, the page locale is an
# explicit Cookie header, and the cookie jar is emptied after every response.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.vinted_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.vinted_fallback_proxy()
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    """A block on direct egress: send new sessions through a residential
    exit for a while (no-op when no fallback country is configured)."""
    global _fallback_until
    if config.vinted_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.VINTED_BLOCK_COOLDOWN


def dump_debug(name, text):
    dbg = os.environ.get("VINTED_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- anonymous token -------------------------------------------------------------
_token = None            # (value, refresh_at)
_token_lock = threading.Lock()


def _jwt_expiry(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:
        return 0.0


def _mint_token(country):
    """Load a light page of one country site and read the token cookie."""
    sess = _session()
    last = "no token cookie"
    for path in TOKEN_PATHS:
        try:
            resp = sess.get(countries.site(country) + path, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            continue
        token = sess.cookies.get(TOKEN_COOKIE)
        sess.cookies.clear()
        if token:
            return token
        if resp.status_code in (403, 429):
            dump_debug("token_blocked", resp.text)
            _note_block()
            _drop_session()
            raise VintedBlocked(f"HTTP {resp.status_code} while opening a session")
        last = f"HTTP {resp.status_code} without a token cookie"
    raise VintedUpstreamError(f"could not open an anonymous session: {last}")


def token(country=countries.DEFAULT_COUNTRY, stale=None):
    """The process-wide anonymous token. `stale` is a value that was just
    refused: it is replaced unless another thread already did."""
    global _token
    now = time.time()
    current = _token
    if current and current[1] > now and current[0] != stale:
        return current[0]
    with _token_lock:
        current = _token
        if current and current[1] > time.time() and current[0] != stale:
            return current[0]
        value = _mint_token(country)
        expires = _jwt_expiry(value)
        refresh_at = time.time() + config.VINTED_TOKEN_MAX_AGE
        if expires:
            refresh_at = min(refresh_at, expires - 300)
        _token = (value, refresh_at)
        return value


# ---- requests --------------------------------------------------------------------

def _error_body(resp):
    try:
        body = resp.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _error_message(body):
    if not body:
        return None
    message = body.get("message")
    return message.strip() if isinstance(message, str) and message.strip() else None


class _TokenRefused(Exception):
    pass


def _classify(resp, label):
    """Raise for a non-2xx answer. Vinted's own JSON errors:
      api      {"code": 100, "message_code": "invalid_authentication_token"}  401
               {"code": 104, "message_code": "not_found"}                     404 (or 400)
               {"code": 106, "message_code": "access_denied"}                 403 login-only
      gateway  {"code": "FORBIDDEN"}                                          403 no/invalid token
               {"code": "NOT_FOUND" | "ITEM_NOT_FOUND"}                       404
               {"code": "INVALID_REQUEST" | "BAD_REQUEST" | ...}              400
    Anything else on 403/429 is a Cloudflare / DataDome block page."""
    status = resp.status_code
    if status in (200, 204):
        return
    body = _error_body(resp)
    code = body.get("code") if body else None
    message_code = body.get("message_code") if body else None
    if status == 401 or code == "FORBIDDEN" or message_code == "invalid_authentication_token":
        raise _TokenRefused()
    if status == 404 or message_code == "not_found" or code in ("NOT_FOUND", "ITEM_NOT_FOUND"):
        raise VintedNotFound(f"{label} not found")
    if status == 403 and message_code == "access_denied":
        raise VintedBadRequest(f"{label} needs a Vinted login")
    if status in (403, 429):
        dump_debug("blocked", resp.text)
        _note_block()
        raise VintedBlocked(f"HTTP {status} on {label}")
    if status in (400, 422):
        raise VintedBadRequest(_error_message(body) or f"upstream rejected {label}")
    raise VintedUpstreamError(f"HTTP {status} on {label}" + (f": {_error_message(body)}" if body else ""))


def _json_of(resp, label):
    body = resp.text or ""
    if resp.status_code == 204 or not body.strip():
        return None
    if not body.lstrip().startswith(("{", "[")):
        dump_debug("nonjson", body)
        raise VintedBlocked(f"{label} returned HTML, not JSON")
    try:
        return resp.json()
    except Exception:
        dump_debug("badjson", body)
        raise VintedUpstreamError(f"could not parse JSON from {label}")


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except VintedUpstreamError as e:      # includes VintedBlocked
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _clean_params(params):
    query = {}
    for key, value in (params or {}).items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        query[key] = value
    return query


def get_json(country, path, params=None, *, language=None, label=None):
    """GET one JSON route of a country site with the anonymous token and
    the market/language Locale header. A refused token is re-minted once."""
    label = label or path
    url = countries.site(country) + path
    query = _clean_params(params)
    state = {"stale": None}

    def once():
        bearer = token(country, stale=state["stale"])
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "authorization": f"Bearer {bearer}",
            "locale": countries.locale(country, language),
            "platform": "web",
            "referer": countries.site(country) + "/",
        }
        sess = _session()
        try:
            resp = sess.get(url, params=query, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise VintedUpstreamError(f"request failed: {type(e).__name__}: {e}")
        finally:
            sess.cookies.clear()
        try:
            _classify(resp, label)
        except _TokenRefused:
            state["stale"] = bearer
            raise VintedBlocked(f"anonymous session refused on {label}")
        return _json_of(resp, label)

    return _retrying(once)


def api(country, path, params=None, **kwargs):
    """GET https://<host>/api/v2<path>."""
    return get_json(country, API + path, params, **kwargs)


def gateway(country, path, params=None, **kwargs):
    """GET https://<host>/web/gateway<path>."""
    return get_json(country, GATEWAY + path, params, **kwargs)


def get_page(country, path, *, language=None, label=None):
    """GET one HTML page of a country site in the given language."""
    label = label or path
    url = countries.site(country) + path

    def once():
        cookie = f"anonymous-iso-locale={countries.locale(country, language)}"
        try:
            cookie += f"; {TOKEN_COOKIE}={token(country)}"
        except VintedUpstreamError:
            pass                      # the page mints its own session
        headers = dict(PAGE_HEADERS, cookie=cookie)
        sess = _session()
        try:
            resp = sess.get(url, headers=headers, timeout=PAGE_TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise VintedUpstreamError(f"request failed: {type(e).__name__}: {e}")
        finally:
            sess.cookies.clear()
        if resp.status_code == 404:
            raise VintedNotFound(f"{label} not found")
        if resp.status_code in (403, 429):
            dump_debug("page_blocked", resp.text)
            _note_block()
            raise VintedBlocked(f"HTTP {resp.status_code} on {label}")
        if resp.status_code != 200:
            raise VintedUpstreamError(f"HTTP {resp.status_code} on {label}")
        return resp.text or ""

    return _retrying(once)


# ---- fan-out ------------------------------------------------------------------------
# A long-lived pool, so its threads keep their curl sessions (and TLS
# connections) between requests.
_pool = ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="vinted")


def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_pool.submit(fn) for fn in fns]
    return [f.result() for f in futures]


def gather(mapping, optional=()):
    """{key: callable} in parallel -> {key: result}. Keys named in
    `optional` yield None instead of failing the set when they raise any
    scraper error (an enrichment must not sink the endpoint)."""
    keys = list(mapping)

    def guarded(key):
        fn = mapping[key]
        if key not in optional:
            return fn

        def run():
            try:
                return fn()
            except (UpstreamError, BadRequest, NotFound):
                return None
        return run

    results = run_parallel([guarded(k) for k in keys])
    return dict(zip(keys, results))


if __name__ == "__main__":
    # Smoke test: python vinted/fetch.py [query] [country]
    q = sys.argv[1] if len(sys.argv) > 1 else "nike"
    cc = sys.argv[2] if len(sys.argv) > 2 else "fr"
    page = gateway(cc, "/svc-catalogue/items", {"search_text": q, "per_page": 3, "page": 1})
    print("search:", [(i["id"], i["title"], i["price"]) for i in page["items"]])
    brands = api(cc, "/brands", {"keyword": q})
    print("brands:", [(b["id"], b["title"]) for b in brands["brands"][:3]])
    html = get_page(cc, f"/items/{page['items'][0]['id']}")
    print("item page:", len(html), "bytes")
