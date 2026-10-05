"""Configuration for the Vinted Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    VINTED_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — direct). Vinted answered 40 parallel
                  searches across 8 country sites from one IP without a single
                  block, so you very likely don't need this. Set it only if
                  you start seeing 403 / 429 at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# The scraper works with Vinted's own anonymous visitor token (what any
# browser gets on its first page load). It lives 24 hours; a fresh one is
# fetched this often, and at once if Vinted ever refuses the current one.
VINTED_TOKEN_MAX_AGE = 6 * 3600

# Block fallback: after a 403 / 429 new sessions may switch to a separate
# proxy for VINTED_BLOCK_COOLDOWN seconds. Off here — with VINTED_PROXY set
# every request already goes through it.
VINTED_BLOCK_COOLDOWN = 900


def vinted_proxy():
    """Proxy URL for a new session (None = direct)."""
    return os.environ.get("VINTED_PROXY") or None


def vinted_fallback_proxy():
    """Proxy for a blocked worker (None = no fallback; see above)."""
    return None
