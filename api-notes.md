# Seller price sources

## Malabar (GraphQL GET, no login)
URL: https://www.malabargoldanddiamonds.com/graphql-magento
query: products(filter: {sku: {eq: "CO-521137"}}) -> items -> price_breakup
Fields: total, metal_charges, making_charges, tax, is_in_stock, purity
Note: metal_charges / making_charges / purity are JSON strings, e.g. {"Gold":"4978.4000"}
Status: tested in Terminal, works

## Joyalukkas (GraphQL GET, no login)
URL: https://www.joyalukkas.in/graphql
query: products(filter: {url_key: {eq: "10-gram-flower-gold-bar-bn21005636"}}) -> items -> price_range -> maximum_price -> final_price -> value
Headers needed: store: default, content-type: application/json, user-agent
Fields: name, sku, stock_status, final_price (no breakup, markup calculated vs MCX)
Status: tested in Terminal, works

## MMTC-PAMP (via Flipkart)
Own site blocked by Akamai (HTTP 403). Virasat coin was a limited collector edition, so swapped to standard Lakshmi 10g bar (999.9)
Flipkart page: price in "offers":{"price":136220,"priceCurrency":"INR" (main product only; ignore "you may also like" prices)
Status: works

## Tanishq (LINK ONLY)
Own site blocks bots; no 10g 24K listing on marketplaces (BigBasket only up to 5g)
Shown on the page as a link with a note, never scraped

## BlueStone (added to replace Tanishq as a live price)
Price in id="our_price_display" ...>1,31,608< (strip commas); backup "price": "131608"
Purity 995
Status: works

## PC Jeweller (REST GET, needs x-api-key)
URL: https://pcj-web-backend-ewchp.ondigitalocean.app/prod/admin/products/variant/69ec93b639cf3ab540eb0c9b
Headers needed: x-api-key (from their public site, store as a secret, never commit), origin, referer, user-agent
Fields: priceBreakup -> metalPrice (price, priceMasterRate per gram), makingCharge (price, %), promotionDiscount (discountAmount)
No total given: final = (metal + making - discount) x 1.03
Checked: computed 130824 matches page price

## PARKED (come back to these)
- ## PARKED (come back to these)
- [x] Tanishq + MMTC-PAMP: decided (Tanishq LINK ONLY, MMTC-PAMP via Flipkart, BlueStone added) - Step 6
- [x] Candere, CaratLane, Joyalukkas: calculate breakup vs MCX - Step 6
- [x] Malabar: unpack JSON-text fields like {"Gold":"4978.4000"} - Step 6
- [x] MCX contract rollover: found automatically from Groww's Gold Ten page - Step 6
- [x] Gold BeES ratio: match MCX price at 3:30 PM IST - Step 6
- [x] PC Jeweller x-api-key: stored as GitHub secret, never in code - Step 8
- [x] .venv kept off GitHub via .gitignore - Step 8
- [ ] Flipkart (MMTC-PAMP) returns 429 from GitHub Actions. Watch a few runs; if always failing, make it LINK ONLY - Step 12
- [ ] Bonus: jeweller board rates (Tanishq rate page, Malabar getMetalRate) - Step 13

## MCX Gold Ten (Groww, no login, no checksum needed)
URL: https://groww.in/v1/api/commodity_fo/v1/tr_live_prices/exchange/MCX/segment/COMMODITY/574842/latest
Headers: Accept, X-APP-ID: growwWeb, x-platform: web, Referer, User-Agent
Fields: ltp (live, per 10g at 999), open, high, low, close (yesterday)
574842 = Gold Ten 30 Nov 2026 contract ID. CHANGES at monthly rollover (parked item)
Status: tested in Terminal, works

## MCX Gold Ten intraday chart (Groww, delayed, no login)
URL: https://groww.in/v1/api/commodity_fo/charting_service/v2/chart/delayed/exchange/MCX/segment/COMMODITY/574842/daily?intervalInMinutes=2&minimal=true
Same headers as latest
Returns: candles = [[unix_seconds, price], ...] for today only (about 117 points)
Use for: optional "today" mini chart. NOT for 1-year history (contract too short-lived)
Status: tested in Terminal, works
- [x] Gold BeES ratio: average over several days instead of today only (evening MCX vs afternoon ETF) - Step 6