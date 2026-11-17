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

  * GATEWAY  https://api.<host without www.>/...   (countries.gateway_site)
    2026-10-12: was https://<host>/web/gateway/...; Vinted removed that
    transparent proxy (every path an empty-body 404) and the web client now
    calls the api. subdomain directly. Same Bearer token, same Locale header.
    svc-catalogue/items (search; hard cap 960 results), svc-filters/filters,
    svc-filters/filters/facets, svc-filters/faceted_categories,
    search-bar/v2/suggestions, item-details/more-items/<id> (similar items;
    500s without the Locale header), pricing/public/api/v1/items/<id>/services.

  * PAGE     https://<host>/items/<id>
    The item page: an RSC flight payload of "plugins" (vinted/flight.py) and
    a ld+json Product. The only anonymous source of an item's description,
    attributes, full gallery and breadcrumbs.

Blocks: Cloudflare is in front without a challenge for Chrome TLS. A
403/429 that is NOT one of Vinted's own JSON errors is a block, kept per
surface since 2026-11-11 (see _exit_for): for config.VINTED_BLOCK_COOLDOWN
seconds after one on the server's own IP,
  * the JSON calls (API, GATEWAY, the token mint) ride the Paris gateway exit
    (config.vinted_fallback_proxy() = "gateway:fr"; a fresh gateway address per
    request, the token is not bound to an address), with the residential
    exit behind it: a call's last retry, and every call for a cooldown once
    the gateway failed GATEWAY_FAILURES calls in GATEWAY_FAILURE_WINDOW s;
  * the item PAGE rides a sticky residential exit
    (config.vinted_page_fallback_proxy()): Cloudflare challenges it from gateway
    addresses.
A session follows its tier: when a cooldown ends the thread's next call is
back on the own IP (before, it kept the residential exit until that failed).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  VintedUpstreamError  transport failure / 5xx              — retryable
  VintedRouteMissing   404 WITHOUT Vinted's own not-found body (route moved,
                       proxy removed) -> 502, not retried
  VintedBlocked        403 / 429 block page, token refused  — retryable on a new exit / token
  VintedBadRequest     upstream 400 / 422                    — never retried
  VintedNotFound       404 / missing entity                  — never retried
"""
import base64
import fastjson
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from vinted import countries
from scraper_utils import debug, fanout

IMPERSONATE = "chrome"
API = "/api/v2"
TOKEN_COOKIE = "access_token_web"
# Any path that 404s sets the token cookie on an 18 KB body (the homepage is 2 MB).
TOKEN_PATHS = ("/page-not-found", "/")

TIMEOUT = 40
PAGE_TIMEOUT = 60
FANOUT_WORKERS = 12

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "upgrade-insecure-requests": "1",
}


class VintedUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class VintedBlocked(VintedUpstreamError, Blocked):
    """403 / 429 block page, or the anonymous token was refused — retryable."""


class VintedRouteMissing(VintedUpstreamError):
    """2026-10-12: a 404 that is NOT one of Vinted's own JSON not-found
    answers (empty body, HTML 404 page, gateway "Route not found."): the
    upstream route moved, not the entity. Reported as 502 so the next API
    move is diagnosable instead of looking like "search not found".
    Not retried — the same URL will 404 again."""


class VintedBadRequest(BadRequest):
    """Upstream 400 / 422 — the params were rejected. Never retried."""


class VintedNotFound(NotFound):
    """Entity / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread and SURFACE: the JSON calls (API,
# GATEWAY and the token mint) and the item PAGE each have their own exit.
# Direct egress by default; after a block on a surface its sessions leave the
# server's own IP for a cooldown. Sessions carry no state: auth is the Bearer
# header, the page locale is an explicit Cookie header, and the cookie jar is
# emptied after every response.
JSON, PAGE = "json", "page"
# A session's tier: the configured exit, the surface's fallback exit, or the
# residential exit that stands in for a gateway exit that keeps failing.
OWN, FALLBACK, LAST_RESORT = "own", "fallback", "last resort"
GATEWAY_FAILURES = 3            # this many failed gateway calls ...
GATEWAY_FAILURE_WINDOW = 60     # ... within this many seconds pause the gateway for a cooldown

_local = threading.local()
_fallback_until = {JSON: 0.0, PAGE: 0.0}    # per surface: no new session on the own IP until then
_gateway_failures = []                      # time.time() of the gateway's latest failed calls
_gateway_paused_until = 0.0
_fallback_lock = threading.Lock()


def _exit_for(surface):
    """(tier, exit) of a session this thread builds NOW for `surface`.

    JSON: config.vinted_proxy() when set, else the server's own IP, and
    config.vinted_fallback_proxy() while the surface's block cooldown runs.
    Where that exit is the gateway exit ("gateway:fr"), a call's last retry and
    every call while the gateway is paused (_note_failure) ride the
    residential exit config.vinted_page_fallback_proxy() instead, so a
    gateway Vinted refuses degrades to the pre-gateway behaviour.

    PAGE: never the gateway. 2026-11-11: Cloudflare answered /items/<id>
    from gateway addresses with its JS challenge (403, 10.6 KB "Please wait",
    `cf-mitigated: challenge`) 22 times of 28 on the Paris gateway and 8 of
    8 on the US and Frankfurt ones — with or without the token cookie, with
    navigation headers, as an `rsc: 1` request — while the same gateways
    served every JSON route and the token mint. The page stays on the own IP
    (or a proxy exit named by config.vinted_proxy()) and moves to the
    residential exit for the cooldown after a block."""
    forced = config.vinted_proxy()
    now = time.time()
    if surface == PAGE:
        if forced and not config.gateway_exit(forced):
            return OWN, forced
        if now < _fallback_until[PAGE]:
            return FALLBACK, config.vinted_page_fallback_proxy()
        return OWN, None
    if forced:
        tier, exit = OWN, forced
    elif now < _fallback_until[JSON]:
        tier, exit = FALLBACK, config.vinted_fallback_proxy()
    else:
        return OWN, None
    if config.gateway_exit(exit) and (getattr(_local, "last_retry", False) or now < _gateway_paused_until):
        last_resort = config.vinted_page_fallback_proxy()
        if last_resort:
            return LAST_RESORT, last_resort
    return tier, exit


def _sessions():
    held = getattr(_local, "sessions", None)
    if held is None:
        held = _local.sessions = {}
    return held


def _session(surface=JSON):
    """The thread's session for `surface`, rebuilt when its tier changed.
    2026-11-11: a session used to live until its next failure, so a thread
    that took a residential exit during a cooldown stayed on it long after
    the cooldown had ended."""
    sessions = _sessions()
    tier, exit = _exit_for(surface)
    held = sessions.get(surface)
    if held is not None and held["tier"] != tier:
        _drop_session(surface)
        held = None
    if held is None:
        # None (direct), a proxy URL, or "gateway" / "gateway:fr" (an exit_gateway.Session:
        # the same get / headers / cookies.get / cookies.clear surface)
        sess = egress.new_session(exit, impersonate=IMPERSONATE)
        sess.headers["accept-language"] = egress.accept_language(exit)
        held = sessions[surface] = {"tier": tier, "exit": exit, "session": sess}
    return held["session"]


def _drop_session(surface=JSON):
    held = _sessions().pop(surface, None)
    if held is not None:
        try:
            held["session"].close()
        except Exception:
            pass


def _held_exit(surface):
    """(a session is held, its exit) for the thread's `surface` session."""
    held = _sessions().get(surface)
    return (True, held["exit"]) if held else (False, None)


def _note_block(surface=JSON):
    """A 403 / 429 block page on the server's own IP: new sessions of that
    surface ride its fallback exit for a while (no-op when none is
    configured). A block on any other exit only costs the call a fresh one
    (_retrying), and the gateway counts its own failures (_note_failure)."""
    held, exit = _held_exit(surface)
    if not held or exit is not None:
        return
    fallback = config.vinted_page_fallback_proxy() if surface == PAGE else config.vinted_fallback_proxy()
    if fallback is not None:
        with _fallback_lock:
            _fallback_until[surface] = time.time() + config.VINTED_BLOCK_COOLDOWN


def _note_failure(surface):
    """A retryable failure of one attempt. On the gateway exit: GATEWAY_FAILURES
    of them inside GATEWAY_FAILURE_WINDOW seconds (a block page, an 
    gateway error, a timeout) pause it for the cooldown, and the JSON calls
    ride the residential exit meanwhile."""
    global _gateway_paused_until
    held, exit = _held_exit(surface)
    if not held or not config.gateway_exit(exit):
        return
    now = time.time()
    with _fallback_lock:
        _gateway_failures[:] = [t for t in _gateway_failures if now - t < GATEWAY_FAILURE_WINDOW] + [now]
        if len(_gateway_failures) < GATEWAY_FAILURES or config.vinted_page_fallback_proxy() is None:
            return
        del _gateway_failures[:]
        _gateway_paused_until = now + config.VINTED_BLOCK_COOLDOWN
    print(f"vinted: the gateway exit failed {GATEWAY_FAILURES} calls in {GATEWAY_FAILURE_WINDOW} s, "
          f"JSON calls ride the residential exit for {config.VINTED_BLOCK_COOLDOWN} s")


def dump_debug(name, text):
    debug.dump("VINTED_DEBUG_DIR", name, text, encoding="utf-8")


# ---- anonymous token -------------------------------------------------------------
_token = None            # (value, refresh_at)
_token_lock = threading.Lock()


def _jwt_expiry(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(fastjson.loads(base64.urlsafe_b64decode(payload)).get("exp") or 0)
    except Exception:
        return 0.0


def _mint_token(country):
    """Load a light page of one country site and read the token cookie. It
    rides the JSON session: the 404 page is not challenged on the gateway
    exit (unlike the item page), and the token it sets works from any
    address."""
    sess = _session(JSON)
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
            _note_block(JSON)
            _note_failure(JSON)     # here, not in _retrying: the session is gone by then
            _drop_session(JSON)
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
               {"code": "NOT_FOUND", "message": "Route not found."}           404 unknown ROUTE
    A 404 with none of these bodies (empty / HTML) is a missing route too.
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
    # 2026-10-12: a bare `status == 404` used to mean "entity missing", so
    # the removal of /web/gateway surfaced as "search not found" / "status
    # not found" on every gateway route. Only Vinted's own not-found bodies
    # are a 404 now; any other 404 is a moved/removed route -> 502.
    message = _error_message(body) or ""
    route_missing = code == "NOT_FOUND" and "route not found" in message.lower()
    if not route_missing and (message_code == "not_found" or code in ("NOT_FOUND", "ITEM_NOT_FOUND")):
        raise VintedNotFound(f"{label} not found")
    if status == 404:
        dump_debug("route_missing", resp.text)
        raise VintedRouteMissing(f"HTTP 404 on {label} without a Vinted not-found body "
                                 f"({resp.url}): upstream route moved")
    if status == 403 and message_code == "access_denied":
        raise VintedBadRequest(f"{label} needs a Vinted login")
    if status in (403, 429):
        dump_debug("blocked", resp.text)
        _note_block(JSON)
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


def _retrying(fn, surface=JSON):
    """fn() up to config.MAX_RETRIES times, each retry on a fresh session of
    `surface`. The last retry of a JSON call leaves the gateway exit for the
    residential exit (_exit_for), and the session built for it is replaced
    on the thread's next call."""
    last = None
    try:
        for attempt in range(1, config.MAX_RETRIES + 1):
            _local.last_retry = surface == JSON and 1 < attempt == config.MAX_RETRIES
            try:
                return fn()
            except VintedRouteMissing:
                raise
            except VintedUpstreamError as e:      # includes VintedBlocked
                last = e
                if not getattr(e, "token_only", False):
                    _note_failure(surface)
                _drop_session(surface)
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
        raise last
    finally:
        _local.last_retry = False


def _clean_params(params):
    query = {}
    for key, value in (params or {}).items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        query[key] = value
    return query


def get_json(country, path, params=None, *, base=None, language=None, label=None):
    """GET one JSON route of a country site (`base` defaults to its www
    origin) with the anonymous token and the market/language Locale header.
    A refused token is re-minted once."""
    label = label or path
    url = (base or countries.site(country)) + path
    query = _clean_params(params)
    state = {"stale": None}

    def once():
        bearer = token(country, stale=state["stale"])
        headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {bearer}",
            "locale": countries.locale(country, language),
            "platform": "web",
            "origin": countries.site(country),
            "referer": countries.site(country) + "/",
        }
        sess = _session(JSON)
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
            refused = VintedBlocked(f"anonymous session refused on {label}")
            refused.token_only = True       # the exit answered: not a gateway failure (_retrying)
            raise refused
        return _json_of(resp, label)

    return _retrying(once)


def api(country, path, params=None, **kwargs):
    """GET https://<host>/api/v2<path>."""
    return get_json(country, API + path, params, **kwargs)


def gateway(country, path, params=None, **kwargs):
    """GET https://api.<host><path> (2026-10-12: was <host>/web/gateway<path>)."""
    return get_json(country, path, params, base=countries.gateway_site(country), **kwargs)


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
        sess = _session(PAGE)
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
            _note_block(PAGE)
            raise VintedBlocked(f"HTTP {resp.status_code} on {label}")
        if resp.status_code != 200:
            raise VintedUpstreamError(f"HTTP {resp.status_code} on {label}")
        return resp.text or ""

    return _retrying(once, PAGE)


# ---- fan-out ------------------------------------------------------------------------
# A long-lived pool, so its threads keep their curl sessions (and TLS
# connections) between requests.
_pool = ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="vinted")


def run_parallel(fns):
    return fanout.on_pool(_pool, fns)


def gather(mapping, optional=()):
    """{key: callable} in parallel -> {key: result}. Keys named in
    `optional` yield None instead of failing the set when they raise any
    scraper error (an enrichment must not sink the endpoint)."""
    return fanout.gather_optional(run_parallel, mapping, optional, (UpstreamError, BadRequest, NotFound))


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
