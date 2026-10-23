# 👜 Vinted Scraper

Vinted Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Vinted data for free.

## ✨ What Can I Get?

- 👜 **Every detail of a listing** — description, photos, brand, size, condition, price with fees, availability & seller
- 🔍 **Search 26 Vinted country sites** — filter by brand, size, condition, colour, material & price
- 🧑 **Full seller profiles** — rating, reviews, items sold, location, followers & the whole wardrobe
- 🏷️ **2,900+ categories and every filter ID** — brands, sizes, colours, conditions & materials

## 🎥 Example: A Full Vinted Listing

```json
{
  "id": "10164542772",
  "title": "Hermes Birkin ostrich Vintage",
  "link": "https://www.vinted.fr/items/10164542772-hermes-birkin-ostrich-vintage",
  "description": "Used vintage birkin 30 in good condition, some scratches on corners but for this gorgeous vintage birkin. Come with original orange dusbag",
  "brand": { "id": "4785", "name": "Hermès", "link": "https://www.vinted.fr/brand/4785-hermes" },
  "condition": "Good",
  "colors": ["Brown"],
  "materials": ["Leather"],
  "availability": "available",
  "can_buy": true,
  "favourites_count": 78,
  "uploaded_ago": "a week ago",
  "pricing": {
    "amount": 14900.0,
    "currency": "EUR",
    "buyer_protection_fee": 745.7,
    "total_amount": 15645.7,
    "shipping_amount": 3.29,
    "total_with_shipping_amount": 15648.99
  },
  "category": { "id": "156", "name": "Handbags", "path": ["Women", "Bags", "Handbags"] },
  "photos": [
    {
      "id": "02_0045a_qvjD2s17tHH7M4gzaG8PqcqV",
      "link": "https://images1.vinted.net/t/02_0045a_qvjD2s17tHH7M4gzaG8PqcqV/f800/5d30532e.webp?s=e82f2fb862cf7c9ae8f263029e03f298fc68da90",
      "width": 600,
      "height": 800,
      "is_main": true
    }
  ],
  "seller": {
    "id": "3137476875",
    "username": "tigerlilly020",
    "link": "https://www.vinted.fr/member/3137476875-tigerlilly020",
    "rating": 4.9,
    "feedback_count": 43,
    "items_count": 111,
    "sold_items_count": 43,
    "followers_count": 40,
    "location": { "city": "Amsterdam", "country_code": "NL", "country": "Netherlands" },
    "last_seen_at": "2026-10-05T07:11:58Z",
    "badges": ["active_lister"]
  },
  "buyer_protection": { "amount": 745.7, "fixed_amount": 0.7, "percent_of_price": 5.0 },
  "shipping": { "amount": 3.29, "from_amount": 2.99, "is_free": false, "has_multiple_options": true }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Vinted Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/vinted-scraper
cd vinted-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/items/details?item=10164542772"
```

```json
{
  "item": {
    "id": "10164542772",
    "title": "Hermes Birkin ostrich Vintage",
    "link": "https://www.vinted.fr/items/10164542772-hermes-birkin-ostrich-vintage",
    "brand": { "id": "4785", "name": "Hermès", "link": "https://www.vinted.fr/brand/4785-hermes" },
    "condition": "Good",
    "colors": ["Brown"],
    "materials": ["Leather"],
    "availability": "available",
    "favourites_count": 78,
    "pricing": {
      "amount": 14900.0,
      "currency": "EUR",
      "buyer_protection_fee": 745.7,
      "total_amount": 15645.7
    },
    "category": { "id": "156", "name": "Handbags", "path": ["Women", "Bags", "Handbags"] },
    "seller": { "id": "3137476875", "username": "tigerlilly020", "rating": 4.9, "feedback_count": 43 }
  }
}
```

All 20 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

20 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Item Details | `/items/details` | Everything about one listing in a single call |
| Search Items | `/search` | Up to 96 listings per page with every Vinted filter |
| Search Filters | `/search/filters` | Filter options with live item counts for any search |
| Autocomplete | `/autocomplete` | What Vinted's search box suggests as you type |
| Similar Items | `/items/similar` | Up to 24 listings similar to an item |
| Item Shipping & Fees | `/items/shipping` | Buyer Protection fee, delivery price and totals |
| Seller Details | `/sellers/details` | Rating, feedback counts, items sold, location, verification |
| Seller Items | `/sellers/items` | A seller's whole wardrobe, sortable by price or date |
| Seller Feedback | `/sellers/feedback` | Reviews with text, rating, reviewer and a rating summary |
| Seller Followers / Following | `/sellers/followers`, `/sellers/following` | Who follows a seller, and who they follow |
| Search Sellers | `/sellers/search` | Find members by username |
| Search Brands / Brand Details | `/brands/search`, `/brands/details` | Brand IDs with listing and follower counts |
| Categories | `/categories` | The full category tree, or any branch of it |
| Sizes / Colors / Conditions / Materials | `/sizes`, `/colors`, `/conditions`, `/materials` | Every ID the search filters take |
| Countries | `/countries` | The 26 Vinted sites with currency and languages |

Every endpoint takes `country` (the Vinted site — `fr`, `de`, `gb`, `us`, `pl` and 21 more) and `language` (labels in English by default).

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-vinted-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-vinted-scraper-free-1000-calls/playground) — every required param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-vinted-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/items/details",
    params={"item": "10164542772"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Vinted Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Vinted%20Scraper%20API.)

[![Ask Us by Email about Vinted Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Vinted%20Scraper%20API&body=I%20need%20help%20using%20the%20Vinted%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/vinted-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/vinted-scraper)
