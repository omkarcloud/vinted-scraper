"""The 20 Vinted endpoints. Every path is served with and without the
`/vinted` prefix, so code generated against the hosted API on RapidAPI (paths
like /items/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in vinted/schemas.py (the
same ones the hosted API uses): ONE param per input — `item`, `brand` and
`category` take an id or a Vinted link, `seller` a username, a member id or a
profile link, and `query` on /search takes text or a full Vinted catalog
link. Unknown params are rejected with a 400 so typos surface.

Every endpoint takes `country` (the Vinted site: fr, de, gb, us, pl ...; a
link's own site when omitted, else fr) and `language` (default en). Lists
page with `page` + `per_page` (count / total_pages / next / previous in the
response)."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from vinted import brands, items, reference, search, sellers
from vinted import schemas as S
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Hermès" would arrive as "HermÃ¨s")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{request.path}?{urlencode(query)}"


def paginate(result, params):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next /
    previous first, then the data."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = int(pagination.get("page") or params.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(params, page + 1 if page < total_pages else None),
        "previous": _page_link(params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema, fn, paginated=False):
    """Validate the query, run the scraper, map errors: bad params -> 400,
    missing entity -> 404, transport/blocks -> 500."""
    params = query_dict()
    data, error = load_query(schema, params)
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the request
        return json_response({"error": f"vinted rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"vinted {label} failed: {e}"}, 500)
    return json_response(paginate(result, params) if paginated else result)


def mount(path, schema, fn, paginated=False):
    """Serve an endpoint at /path and /vinted/path."""
    def handler():
        return call(path.strip("/"), schema, fn, paginated)
    handler.__name__ = "vinted_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/vinted" + path, method="GET")(handler)


P = True   # paginated (page + per_page)
ENDPOINTS = [
    ("/items/details", S.ItemSchema, items.details, False),
    ("/search", S.SearchSchema, search.search, P),
    ("/search/filters", S.SearchFiltersSchema, search.filters, False),
    ("/autocomplete", S.AutocompleteSchema, search.autocomplete, False),
    ("/items/similar", S.ItemSchema, items.similar, False),
    ("/items/shipping", S.ItemSchema, items.shipping, False),
    ("/sellers/details", S.SellerSchema, sellers.details, False),
    ("/sellers/items", S.SellerItemsSchema, sellers.items, P),
    ("/sellers/feedback", S.SellerFeedbackSchema, sellers.feedback, P),
    ("/sellers/followers", S.SellerListSchema, sellers.followers, P),
    ("/sellers/following", S.SellerListSchema, sellers.following, P),
    ("/sellers/search", S.SellerSearchSchema, sellers.search, P),
    ("/brands/search", S.BrandSearchSchema, brands.search, False),
    ("/brands/details", S.BrandSchema, brands.details, False),
    ("/categories", S.CategoriesSchema, reference.categories, False),
    ("/sizes", S.MarketSchema, reference.sizes, False),
    ("/colors", S.MarketSchema, reference.colors, False),
    ("/conditions", S.MarketSchema, reference.conditions, False),
    ("/materials", S.MaterialsSchema, reference.materials, False),
    ("/countries", S.EmptySchema, reference.countries, False),
]

for _path, _schema, _fn, _paginated in ENDPOINTS:
    mount(_path, _schema, _fn, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
