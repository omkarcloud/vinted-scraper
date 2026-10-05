"""Cache TTL per /vinted/* endpoint (cache.py, keyed on the validated params).

Tiers follow how fast Vinted moves each surface: the newest-first feed
gains listings every second and one-off items sell within minutes, a
seller's feedback grows by a few rows a day, and the category / size /
colour catalogues change a few times a year.
"""
from datetime import timedelta

# --- search ------------------------------------------------------------------
# Listings are one-of-a-kind and sell fast; a stale page shows sold items.
SEARCH_CACHE = timedelta(minutes=2)
# Facet counts drift slowly relative to their size.
FILTERS_CACHE = timedelta(minutes=30)
AUTOCOMPLETE_CACHE = timedelta(hours=6)

# --- items -------------------------------------------------------------------
# Availability (sold / reserved) is the field callers poll for.
ITEM_CACHE = timedelta(minutes=3)
SIMILAR_CACHE = timedelta(minutes=10)
SHIPPING_CACHE = timedelta(minutes=30)

# --- sellers -----------------------------------------------------------------
SELLER_CACHE = timedelta(minutes=10)
SELLER_ITEMS_CACHE = timedelta(minutes=5)
FEEDBACK_CACHE = timedelta(minutes=15)
FOLLOWERS_CACHE = timedelta(minutes=30)
SELLER_SEARCH_CACHE = timedelta(minutes=30)

# --- brands / catalogues -----------------------------------------------------
BRAND_CACHE = timedelta(hours=6)
REFERENCE_CACHE = timedelta(days=1)
