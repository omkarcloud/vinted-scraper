"""The 26 Vinted country sites. Each is its own MARKET (own listings, own
currency) served from its own host; the `Locale` request header
(`<language>-<COUNTRY>`) picks both the market and the language of every
label (conditions, colours, categories, sizes). English is served on every
market, so it is the default; `languages` lists what each site's own
language switcher offers (validated 2026-10-05 from /api/v2/languages —
Austria's switcher lists German only, but en-AT answers in English too).
"""

# code: (name, host, currency, [languages], site default language)
_TABLE = {
    "at": ("Austria", "www.vinted.at", "EUR", ["en", "de"], "de"),
    "be": ("Belgium", "www.vinted.be", "EUR", ["en", "fr", "nl", "es"], "fr"),
    "cz": ("Czech Republic", "www.vinted.cz", "CZK", ["en", "cs"], "cs"),
    "de": ("Germany", "www.vinted.de", "EUR", ["en", "de"], "de"),
    "dk": ("Denmark", "www.vinted.dk", "DKK", ["en", "da"], "da"),
    "ee": ("Estonia", "www.vinted.ee", "EUR", ["en", "et"], "et"),
    "es": ("Spain", "www.vinted.es", "EUR", ["en", "es", "fr", "nl"], "es"),
    "fi": ("Finland", "www.vinted.fi", "EUR", ["en", "fi"], "fi"),
    "fr": ("France", "www.vinted.fr", "EUR", ["en", "fr", "es", "nl"], "fr"),
    "gb": ("United Kingdom", "www.vinted.co.uk", "GBP", ["en"], "en"),
    "gr": ("Greece", "www.vinted.gr", "EUR", ["en", "el"], "el"),
    "hr": ("Croatia", "www.vinted.hr", "EUR", ["en", "hr"], "hr"),
    "hu": ("Hungary", "www.vinted.hu", "HUF", ["en", "hu"], "hu"),
    "ie": ("Ireland", "www.vinted.ie", "EUR", ["en"], "en"),
    "it": ("Italy", "www.vinted.it", "EUR", ["en", "it"], "it"),
    "lt": ("Lithuania", "www.vinted.lt", "EUR", ["en", "lt"], "lt"),
    "lu": ("Luxembourg", "www.vinted.lu", "EUR", ["en", "fr", "es", "nl"], "fr"),
    "lv": ("Latvia", "www.vinted.lv", "EUR", ["en", "lv"], "lv"),
    "nl": ("Netherlands", "www.vinted.nl", "EUR", ["en", "nl", "fr", "es"], "nl"),
    "pl": ("Poland", "www.vinted.pl", "PLN", ["en", "pl"], "pl"),
    "pt": ("Portugal", "www.vinted.pt", "EUR", ["en", "pt"], "pt"),
    "ro": ("Romania", "www.vinted.ro", "RON", ["en", "ro"], "ro"),
    "se": ("Sweden", "www.vinted.se", "SEK", ["en", "sv"], "sv"),
    "si": ("Slovenia", "www.vinted.si", "EUR", ["en", "sl"], "sl"),
    "sk": ("Slovakia", "www.vinted.sk", "EUR", ["en", "sk"], "sk"),
    "us": ("United States", "www.vinted.com", "USD", ["en", "es"], "en"),
}

ALIASES = {"uk": "gb"}
DEFAULT_COUNTRY = "fr"
DEFAULT_LANGUAGE = "en"
CODES = sorted(_TABLE)
LANGUAGES = sorted({lang for row in _TABLE.values() for lang in row[3]})

_BY_HOST = {row[1]: code for code, row in _TABLE.items()}
_BY_HOST.update({row[1][4:]: code for code, row in _TABLE.items()})   # without www.


def normalize(code):
    """'UK' -> 'gb'; unknown -> None."""
    code = str(code or "").strip().lower()
    code = ALIASES.get(code, code)
    return code if code in _TABLE else None


def name(code):
    return _TABLE[code][0]


def host(code):
    return _TABLE[code][1]


def site(code):
    return "https://" + _TABLE[code][1]


def currency(code):
    return _TABLE[code][2]


def languages(code):
    return list(_TABLE[code][3])


def default_language(code):
    return _TABLE[code][4]


def locale(code, language=None):
    """The Locale header / anonymous-iso-locale cookie value: 'en-FR'."""
    return f"{language or DEFAULT_LANGUAGE}-{code.upper()}"


def country_of_host(hostname):
    """'www.vinted.co.uk' / 'vinted.fr' -> 'gb' / 'fr'; another site -> None."""
    return _BY_HOST.get(str(hostname or "").strip().lower())


def table():
    return [{"code": code.upper(), "name": row[0], "domain": row[1], "link": "https://" + row[1],
             "currency": row[2], "languages": list(row[3]), "default_language": row[4]}
            for code, row in sorted(_TABLE.items(), key=lambda kv: kv[1][0])]
