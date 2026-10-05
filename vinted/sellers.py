"""/vinted/sellers/* — a member's public profile, wardrobe (active
listings), feedback, followers / following, and member search.

`seller` takes a member id, a username or a profile link. A wardrobe is
listed in full only on the seller's own market (a French seller's wardrobe
is empty on vinted.co.uk), so when neither `country` nor a link names the
site, the seller's home country is used.
"""
from vinted import parsers as P
from vinted.fetch import api, gather
from vinted.shared import market, seller_id, seller_market, seller_raw


def details(seller, country=None, language=None):
    country, language = market(country, language, seller.get("country"))
    user = seller_raw(seller, country, language)
    out = P.seller(user, country)
    try:
        body = api(country, "/user_feedbacks/summary", {"user_id": out["id"]}, language=language,
                   label="feedback summary")
        summary = body.get("user_feedback_summary") if isinstance(body, dict) else None
    except Exception:
        summary = None
    out["feedback_summary"] = P.feedback_summary(summary) if summary else None
    return {"seller": out}


def items(seller, country=None, language=None, sort_by=None, page=1, per_page=48):
    """The seller's wardrobe: active listings (reserved ones are flagged)."""
    country, language = seller_market(seller, country, language)
    sid = seller_id(seller, country)
    body = api(country, f"/wardrobe/{sid}/items",
               {"page": page, "per_page": per_page, "order": sort_by or "relevance"},
               language=language, label=f"seller {sid} items") or {}
    rows = P.item_cards(body.get("items"), country)
    return {"seller_id": sid, "country": country.upper(), "sort_by": sort_by or "relevance",
            "pagination": P.pagination(body.get("pagination"), page, per_page), "items": rows}


def feedback(seller, country=None, language=None, type="all", page=1, per_page=20):
    """Reviews left for the seller, newest first. type: all | member
    (written by a buyer / seller) | automatic (Vinted's own "sale completed
    successfully" rows)."""
    country, language = seller_market(seller, country, language)
    sid = seller_id(seller, country)
    parts = gather({
        "list": lambda: api(country, "/user_feedbacks",
                            {"user_id": sid, "page": page, "per_page": per_page, "by": type},
                            language=language, label=f"seller {sid} feedback"),
        "summary": lambda: api(country, "/user_feedbacks/summary", {"user_id": sid},
                               language=language, label="feedback summary"),
    }, optional=("summary",))
    body = parts["list"] or {}
    rows = [f for f in (P.feedback(r, country) for r in (body.get("user_feedbacks") or [])) if f]
    summary = (parts.get("summary") or {}).get("user_feedback_summary")
    public_type = {"user": "member", "system": "automatic"}.get(type, "all")
    return {"seller_id": sid, "country": country.upper(), "type": public_type,
            "summary": P.feedback_summary(summary) if summary else None,
            "pagination": P.pagination(body.get("pagination"), page, per_page), "feedback": rows}


def _member_list(seller, country, language, page, per_page, route, label):
    country, language = seller_market(seller, country, language)
    sid = seller_id(seller, country)
    body = api(country, f"/users/{sid}/{route}", {"page": page, "per_page": per_page},
               language=language, label=f"seller {sid} {label}") or {}
    rows = [s for s in (P.seller_row(r, country) for r in (body.get("users") or [])) if s]
    return {"seller_id": sid, "country": country.upper(),
            "pagination": P.pagination(body.get("pagination"), page, per_page), "sellers": rows}


def followers(seller, country=None, language=None, page=1, per_page=20):
    return _member_list(seller, country, language, page, per_page, "followers", "followers")


def following(seller, country=None, language=None, page=1, per_page=20):
    return _member_list(seller, country, language, page, per_page, "followed_users", "following")


def search(query, country=None, language=None, page=1, per_page=20):
    """Members whose username matches the text."""
    country, language = market(country, language)
    body = api(country, "/users", {"search_text": query, "page": page, "per_page": per_page},
               language=language, label="seller search") or {}
    rows = [s for s in (P.seller_row(r, country) for r in (body.get("users") or [])) if s]
    return {"query": query, "country": country.upper(),
            "pagination": P.pagination(body.get("pagination"), page, per_page), "sellers": rows}
