"""Marshmallow request schemas for every /vinted/* route. Generic fields
come from the shared schema_fields.py; this module adds the Vinted
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    item      an item id (10252963967) OR a vinted item link
    seller    a member id, a username OR a vinted profile link
    brand     a brand id (53) OR a vinted brand link
    category  a category id (1206) OR a vinted catalog link
    query     free text OR (on /vinted/search) any vinted catalog link,
              whose own filters are then applied

Every route takes `country` (the Vinted site: fr, de, gb, us, pl ...; a
link's own site is used when omitted, else fr) and `language` (the label
language, default en).
"""
import re

from marshmallow import ValidationError, fields, validates_schema

from schema_fields import (BaseSchema, ChoiceField, PageField, PageSizeField, Price,
                           QueryField, RefField, StrippedString)
from vinted import countries, refs

MAX_SEARCH_RESULTS = 960        # the catalogue serves 10 pages of 96, nothing beyond
_FILTER_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_ID_RE = re.compile(r"^\d{1,15}$")


# ---- fields ------------------------------------------------------------------------

class CountryField(StrippedString):
    """Vinted country site: ISO code (fr, de, gb, us ...; uk = gb)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        code = countries.normalize(value)
        if code is None:
            raise ValidationError(f"Must be a Vinted country: {', '.join(countries.CODES)}.")
        return code


class LanguageField(StrippedString):
    """Label language (en, fr, de ...). Which ones a site serves is checked
    against the effective country in the endpoint."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        value = value.lower().split("-")[0].split("_")[0]
        if value not in countries.LANGUAGES:
            raise ValidationError(f"Must be one of: {', '.join(countries.LANGUAGES)}.")
        return value


class ItemField(RefField):
    resolver = staticmethod(refs.resolve_item)


class SellerField(RefField):
    resolver = staticmethod(refs.resolve_seller)


class BrandField(RefField):
    resolver = staticmethod(refs.resolve_brand)


class CategoryField(RefField):
    resolver = staticmethod(refs.resolve_category)


class IdListField(fields.Field):
    """'53, 14' -> ['53', '14'] (numeric Vinted ids, deduped, max 50)."""

    def __init__(self, max_items=50, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            part = raw.strip()
            if not part:
                continue
            if not _ID_RE.match(part):
                raise ValidationError(f"'{part}' is not a numeric id.")
            if part not in out:
                out.append(part)
        if len(out) > self.max_items:
            raise ValidationError(f"At most {self.max_items} ids.")
        return out or None


class CategoryListField(IdListField):
    """Category ids and/or vinted catalog links, comma-separated."""

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            part = raw.strip()
            if not part:
                continue
            try:
                category_id = refs.resolve_category(part)
            except ValueError as e:
                raise ValidationError(str(e))
            if category_id not in out:
                out.append(category_id)
        if len(out) > self.max_items:
            raise ValidationError(f"At most {self.max_items} categories.")
        return out or None


class FiltersField(fields.Field):
    """Category-specific filters as 'code:id,id;code:id' — e.g.
    'brand_collection:4041;internal_memory_capacity:1291' for iPhone 11 /
    128 GB. Codes and option ids come from /vinted/search/filters."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out = {}
        for group in str(value).split(";"):
            group = group.strip()
            if not group:
                continue
            code, sep, ids = group.partition(":")
            code = code.strip().lower()
            if not sep or not _FILTER_CODE_RE.match(code):
                raise ValidationError("Must look like code:id,id;code:id (codes from /vinted/search/filters).")
            for raw in ids.split(","):
                part = raw.strip()
                if not part:
                    continue
                if not _ID_RE.match(part):
                    raise ValidationError(f"'{part}' is not a numeric option id.")
                if part not in out.setdefault(code, []):
                    out[code].append(part)
            if not out.get(code):
                raise ValidationError(f"Filter '{code}' has no option ids.")
        if len(out) > 15:
            raise ValidationError("At most 15 filters.")
        return out or None


def _sort_field():
    return ChoiceField(list(refs.SORT_ORDERS))


# ---- schemas ----------------------------------------------------------------------------

class MarketSchema(BaseSchema):
    country = CountryField()
    language = LanguageField()


class _FilterParams(MarketSchema):
    query = StrippedString(required=False, load_default=None,
                           metadata={"description": "search text or a vinted catalog link"})
    min_price = Price()
    max_price = Price()
    category_ids = CategoryListField()
    brand_ids = IdListField()
    size_ids = IdListField()
    condition_ids = IdListField()
    color_ids = IdListField()
    material_ids = IdListField()
    pattern_ids = IdListField()
    filters = FiltersField()

    @validates_schema
    def _price_range(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("Must not be greater than max_price.", "min_price")
        query = data.get("query")
        if query and len(query) > 300 and not refs.is_link(query):
            raise ValidationError("Longer than 300 characters.", "query")


class SearchSchema(_FilterParams):
    sort_by = _sort_field()
    # None = "not given", so a link's own page / order can apply
    page = PageField(max_page=MAX_SEARCH_RESULTS, load_default=None)
    per_page = PageSizeField(default=48, max_size=96)

    @validates_schema
    def _depth(self, data, **kwargs):
        if (data.get("page") or 1) * data.get("per_page", 48) > MAX_SEARCH_RESULTS:
            raise ValidationError(f"Vinted serves the first {MAX_SEARCH_RESULTS} results of a search: "
                                  f"page x per_page must not exceed {MAX_SEARCH_RESULTS}. Narrow the search "
                                  "with filters or a price range to reach more items.", "page")


class SearchFiltersSchema(_FilterParams):
    pass


class AutocompleteSchema(MarketSchema):
    query = QueryField(max_length=100)


class ItemSchema(MarketSchema):
    item = ItemField()


class SellerSchema(MarketSchema):
    seller = SellerField()


class SellerItemsSchema(SellerSchema):
    sort_by = _sort_field()
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=48, max_size=96)


class SellerFeedbackSchema(SellerSchema):
    type = ChoiceField({"all": "all", "member": "user", "automatic": "system"}, load_default="all")
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=20, max_size=100)


class SellerListSchema(SellerSchema):
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=20, max_size=100)


class SellerSearchSchema(MarketSchema):
    query = QueryField(max_length=60)
    page = PageField(max_page=100)
    per_page = PageSizeField(default=20, max_size=100)


class BrandSearchSchema(MarketSchema):
    query = QueryField(max_length=80)


class BrandSchema(MarketSchema):
    brand = BrandField()


class CategoriesSchema(MarketSchema):
    category = CategoryField(required=False, load_default=None)


class MaterialsSchema(MarketSchema):
    category = CategoryField(required=False, load_default=None)


class EmptySchema(BaseSchema):
    pass
