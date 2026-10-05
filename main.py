"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The functions live in vinted/ (search, items, sellers, brands,
reference). Item, seller and brand inputs take the same validated refs the
API builds, so go through vinted.refs first.
"""
import json
import os

from vinted import items, refs, search, sellers

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # search with filters: cheapest first, up to 500 EUR, on the French site
    found = search.search(query="louis vuitton bag", max_price=500, sort_by="price_low_to_high", per_page=24)
    save("search_louis_vuitton_bag.json", found)

    # one listing in full — an item id or any vinted item link
    first = found["items"][0]["link"]
    save("item_details.json", items.details(refs.resolve_item(first)))

    # a seller's profile — username, member id or profile link
    save("seller_vintage.json", sellers.details(refs.resolve_seller("vintage")))
