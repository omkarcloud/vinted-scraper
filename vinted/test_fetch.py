"""vinted/fetch.py exit tiering, no network: egress.new_session is faked and
every fake session answers by the exit it was built on.

    python -m pytest vinted/test_fetch.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vinted import fetch  # noqa: E402
from scraper_utils.testing import hosted_only

OWN, GATEWAY, RESIDENTIAL = "own", "gateway:fr", "residential"
BLOCK = "<html><title>Vinted</title>Please wait</html>"


class Resp:
    def __init__(self, status=200, text="{}", url=""):
        self.status_code, self.text, self.url, self.headers = status, text, url, {}

    def json(self):
        return fetch.fastjson.loads(self.text)


class Jar(dict):
    pass


class Net:
    """What each exit answers: {exit kind: status}, default 200. Records
    (exit kind, path) per request and every session built."""

    def __init__(self):
        self.status = {}
        self.calls = []
        self.sessions = []

    def exits(self):
        return [kind for kind, _ in self.calls]


class Session:
    def __init__(self, net, exit):
        self.net, self.exit = net, exit
        self.kind = OWN if exit is None else (exit if exit.startswith("gateway") else RESIDENTIAL)
        self.headers, self.cookies, self.closed = {}, Jar(), False

    def get(self, url, **kw):
        path = "/" + url.split("/", 3)[3]
        self.net.calls.append((self.kind, path))
        status = self.net.status.get(self.kind, 200)
        if path == "/page-not-found" and status == 200:
            self.cookies[fetch.TOKEN_COOKIE] = "minted-on-" + self.kind
            return Resp(404, "<html>not found</html>", url)
        if status != 200:
            return Resp(status, BLOCK, url)
        return Resp(200, "<html>item</html>" if path.startswith("/items/") else '{"ok": true}', url)

    def close(self):
        self.closed = True


@pytest.fixture
def net(monkeypatch):
    net = Net()

    def new_session(exit=None, impersonate="chrome", **kw):
        sess = Session(net, exit)
        net.sessions.append(sess)
        return sess

    monkeypatch.setattr(fetch.egress, "new_session", new_session)
    monkeypatch.setattr(fetch.config, "residential_proxy", lambda country, states=None: f"http://exit.{country}")
    monkeypatch.setattr(fetch.config, "VINTED_PROXY_COUNTRY", None)
    monkeypatch.setattr(fetch.config, "VINTED_FALLBACK_PROXY_COUNTRY", "gateway:fr")
    monkeypatch.setattr(fetch.config, "VINTED_PAGE_FALLBACK_PROXY_COUNTRY", "fr")
    monkeypatch.setattr(fetch.config, "MAX_RETRIES", 3)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(fetch, "_fallback_until", {fetch.JSON: 0.0, fetch.PAGE: 0.0})
    monkeypatch.setattr(fetch, "_gateway_failures", [])
    monkeypatch.setattr(fetch, "_gateway_paused_until", 0.0)
    monkeypatch.setattr(fetch, "_token", ("token", fetch.time.time() + 3600))
    fetch._local.sessions = {}
    fetch._local.last_retry = False
    yield net
    fetch._local.sessions = {}


def search():
    return fetch.gateway("fr", "/svc-catalogue/items", {"search_text": "nike"})


def page():
    return fetch.get_page("fr", "/items/1")


@hosted_only
def test_everything_rides_the_own_ip_until_a_block(net):
    assert search() == {"ok": True} and page() == "<html>item</html>" and search() == {"ok": True}
    assert net.exits() == [OWN, OWN, OWN]
    assert len(net.sessions) == 2           # one per surface, kept between calls


@hosted_only
def test_a_json_block_moves_the_json_calls_to_the_gateway_and_leaves_the_page(net):
    net.status[OWN] = 403
    assert search() == {"ok": True}
    assert net.exits() == [OWN, GATEWAY]
    net.status[OWN] = 200
    assert search() == {"ok": True} and page() == "<html>item</html>"
    assert net.exits()[2:] == [GATEWAY, OWN]            # the cooldown is the JSON surface's only
    assert fetch._fallback_until[fetch.PAGE] == 0.0


@hosted_only
def test_a_page_block_moves_the_page_to_the_residential_exit_never_the_gateway(net):
    net.status[OWN] = 403
    assert page() == "<html>item</html>"
    assert net.exits() == [OWN, RESIDENTIAL]
    assert fetch._fallback_until[fetch.JSON] == 0.0
    net.status[OWN] = 200
    assert search() == {"ok": True}
    assert net.exits()[2:] == [OWN]


@hosted_only
def test_the_page_stays_off_a_gateway_named_for_every_session(net, monkeypatch):
    monkeypatch.setattr(fetch.config, "VINTED_PROXY_COUNTRY", "gateway:fr")
    assert search() == {"ok": True} and page() == "<html>item</html>"
    assert net.exits() == [GATEWAY, OWN]
    monkeypatch.setattr(fetch.config, "VINTED_PAGE_FALLBACK_PROXY_COUNTRY", "gateway:fr")
    assert fetch.config.vinted_page_fallback_proxy() is None


@hosted_only
def test_sessions_return_to_the_own_ip_when_the_cooldown_ends(net):
    net.status[OWN] = 403
    search(), page()
    net.status[OWN] = 200
    fetch._fallback_until[fetch.JSON] = fetch._fallback_until[fetch.PAGE] = 0.0     # both cooldowns over
    del net.calls[:]
    search(), page()
    assert net.exits() == [OWN, OWN]
    assert [s.closed for s in net.sessions if s.kind != OWN] == [True, True]


@hosted_only
def test_a_calls_last_retry_leaves_a_failing_gateway_for_the_residential_exit(net):
    fetch._fallback_until[fetch.JSON] = fetch.time.time() + 900
    net.status[GATEWAY] = 403
    assert search() == {"ok": True}
    assert net.exits() == [GATEWAY, GATEWAY, RESIDENTIAL]
    assert fetch._gateway_paused_until == 0.0           # two failures: not paused yet
    net.status[GATEWAY] = 200
    assert search() == {"ok": True}
    assert net.exits()[3:] == [GATEWAY]                 # the last-retry session is not kept


@hosted_only
def test_a_gateway_that_keeps_failing_is_paused_for_a_cooldown(net):
    fetch._fallback_until[fetch.JSON] = fetch.time.time() + 900
    net.status[GATEWAY] = 403
    search(), search()
    # call 1: gateway twice, then its last retry; call 2: the third failure pauses the gateway
    assert net.exits() == [GATEWAY, GATEWAY, RESIDENTIAL, GATEWAY, RESIDENTIAL]
    assert fetch._gateway_paused_until > fetch.time.time()
    del net.calls[:]
    assert search() == {"ok": True}
    assert net.exits() == [RESIDENTIAL]
    fetch._gateway_paused_until = 0.0
    net.status[GATEWAY] = 200
    assert search() == {"ok": True}
    assert net.exits()[1:] == [GATEWAY]


@hosted_only
def test_a_block_on_a_fallback_exit_does_not_restart_the_cooldown(net):
    fetch._fallback_until[fetch.PAGE] = until = fetch.time.time() + 5
    net.status[RESIDENTIAL] = 403
    with pytest.raises(fetch.VintedBlocked):
        page()
    assert net.exits() == [RESIDENTIAL] * 3 and fetch._fallback_until[fetch.PAGE] == until


@hosted_only
def test_a_residential_fallback_country_still_works_for_the_json_calls(net, monkeypatch):
    monkeypatch.setattr(fetch.config, "VINTED_FALLBACK_PROXY_COUNTRY", "fr")
    net.status[OWN] = 403
    assert search() == {"ok": True} and search() == {"ok": True}
    assert net.exits() == [OWN, RESIDENTIAL, RESIDENTIAL]


@hosted_only
def test_no_fallback_configured_keeps_every_retry_on_the_own_ip(net, monkeypatch):
    monkeypatch.setattr(fetch.config, "VINTED_FALLBACK_PROXY_COUNTRY", None)
    monkeypatch.setattr(fetch.config, "VINTED_PAGE_FALLBACK_PROXY_COUNTRY", None)
    net.status[OWN] = 429
    with pytest.raises(fetch.VintedBlocked):
        search()
    with pytest.raises(fetch.VintedBlocked):
        page()
    assert net.exits() == [OWN] * 6


@hosted_only
def test_the_token_mint_rides_the_json_session(net, monkeypatch):
    monkeypatch.setattr(fetch, "_token", None)
    fetch._fallback_until[fetch.JSON] = fetch.time.time() + 900
    assert page() == "<html>item</html>"
    assert net.calls == [(GATEWAY, "/page-not-found"), (OWN, "/items/1")]
    assert fetch._token[0] == "minted-on-gateway:fr"


@hosted_only
def test_a_blocked_mint_on_the_gateway_counts_as_a_gateway_failure(net, monkeypatch):
    monkeypatch.setattr(fetch, "_token", None)
    fetch._fallback_until[fetch.JSON] = fetch.time.time() + 900
    net.status[GATEWAY] = 403
    assert search() == {"ok": True}
    # two mints refused on the gateway, then the last retry mints and searches on the residential exit
    assert net.exits() == [GATEWAY, GATEWAY, RESIDENTIAL, RESIDENTIAL]
    assert len(fetch._gateway_failures) == 2 and fetch._token[0] == "minted-on-residential"


@hosted_only
def test_a_refused_token_is_not_a_gateway_failure(net, monkeypatch):
    fetch._fallback_until[fetch.JSON] = fetch.time.time() + 900
    answers = [Resp(401, '{"code": 100, "message_code": "invalid_authentication_token"}')]
    plain = Session.get
    monkeypatch.setattr(Session, "get", lambda self, url, **kw: (plain(self, url, **kw), answers.pop())[1]
                        if answers and "page-not-found" not in url else plain(self, url, **kw))
    assert search() == {"ok": True}
    assert net.calls == [(GATEWAY, "/svc-catalogue/items"), (GATEWAY, "/page-not-found"), (GATEWAY, "/svc-catalogue/items")]
    assert fetch._gateway_failures == [] and fetch._token[0] == "minted-on-gateway:fr"
