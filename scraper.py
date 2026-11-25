import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

IST = timezone(timedelta(hours=5, minutes=30))  # India Standard Time

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
GST_RATE = 0.03  # GST on gold in India is 3%
STALE_LIMIT = timedelta(hours=3)  # how long we keep showing a seller's last good price


# ---------- Helpers ----------

def fetch_html(url):
    """Download a web page as text, following redirects like a browser."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.text


def find_number(pattern, text):
    """Search text for a pattern and return the number it captures, or None."""
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


# ---------- MCX ----------

def get_current_contract():
    """Find which Gold Ten contract Groww currently treats as the main one."""
    html = fetch_html("https://groww.in/commodities/futures/mcx_goldten")
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        data = json.loads(match.group(1))
        details = data["props"]["pageProps"]["staticData"]["contractDetails"]
        token, contract_id = str(details["token"]), details["contractId"]
    else:
        # Backup: search the page text directly
        backup = re.search(r'"contractDetails":\{"token":"?(\d+)"?,"contractId":"([^"]+)"', html)
        if not backup:
            raise RuntimeError("Could not find the current Gold Ten contract on Groww")
        token, contract_id = backup.group(1), backup.group(2)
    return {"token": token, "contract_id": contract_id}


def get_mcx_price(contract):
    """Fetch the live MCX Gold Ten price (rupees per 10g, 999 purity) from Groww."""
    url = f"https://groww.in/v1/api/commodity_fo/v1/tr_live_prices/exchange/MCX/segment/COMMODITY/{contract['token']}/latest"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-APP-ID": "growwWeb",
        "x-platform": "web",
        "Referer": f"https://groww.in/commodities/futures/mcx_goldten/{contract['contract_id'].lower()}",
        "User-Agent": USER_AGENT,
    }
    data = requests.get(url, headers=headers, timeout=15).json()
    price = data.get("ltp")
    if not price:
        raise RuntimeError(f"Groww returned no live price for {contract['contract_id']}")
    return price
# ---------- Sellers: read from the page ----------

def scrape_candere(url):
    html = fetch_html(url)
    return {
        "final_price": find_number(r'"GCS000010","name":"[^"]*","price":([\d.]+)', html),
        "seller_gold_value": find_number(r'"GCS000010","code":"yellow-gold","color":"[^"]*","price":([\d.]+)', html),
        "seller_making": find_number(r'"GCS000010","making_charge":([\d.]+)', html),
    }


def scrape_caratlane(url):
    html = fetch_html(url)
    return {"final_price": find_number(r'itemProp="price" content="([\d.]+)"', html)}


def scrape_senco(url):
    html = fetch_html(url)
    final_price = find_number(r'"@type":"Offer","priceCurrency":"INR","price":([\d.]+)', html)
    gst = find_number(r'"gst_value":([\d.]+)', html)
    making = re.search(r'"([a-z_]+)":([\d.]+),"gst_percent"', html)
    result = {"final_price": final_price}
    if making and final_price and gst:
        result["making_label"] = making.group(1)
        result["seller_making"] = float(making.group(2))
        result["seller_gold_value"] = final_price - gst - result["seller_making"]
    return result


# ---------- Sellers: read from hidden feeds ----------

def scrape_malabar(url):
    sku = re.search(r"sku=([^&]+)", url).group(1)
    query = ("query products($filter: ProductAttributeFilterInput) { products(filter: $filter) "
             "{ items { name sku price_breakup { is_in_stock total metal_charges making_charges } } } }")
    params = {"query": query, "variables": json.dumps({"filter": {"sku": {"eq": sku}}})}
    response = requests.get("https://www.malabargoldanddiamonds.com/graphql-magento",
                            params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    breakup = response.json()["data"]["products"]["items"][0]["price_breakup"]
    if isinstance(breakup, list):
        breakup = breakup[0]
    # These two fields are text with data inside, like {"Gold":"124460.0000"}
    gold = float(json.loads(breakup["metal_charges"])["Gold"])
    making = float(json.loads(breakup["making_charges"])["Gold"])
    return {
        "final_price": float(breakup["total"]),
        "seller_gold_value": gold,
        "seller_making": making,
        "in_stock": breakup["is_in_stock"],
    }


def scrape_joyalukkas(url):
    url_key = url.rstrip("/").split("/")[-1].replace(".html", "")
    query = ("query getProduct($urlKey: String!) { products(filter: {url_key: {eq: $urlKey}}) "
             "{ items { name sku stock_status price_range { maximum_price { final_price { value } } } } } }")
    params = {"query": query, "variables": json.dumps({"urlKey": url_key})}
    headers = {"User-Agent": USER_AGENT, "store": "default", "content-type": "application/json"}
    response = requests.get("https://www.joyalukkas.in/graphql", params=params, headers=headers, timeout=20)
    item = response.json()["data"]["products"]["items"][0]
    return {
        "final_price": float(item["price_range"]["maximum_price"]["final_price"]["value"]),
        "in_stock": item["stock_status"] == "IN_STOCK",
    }


PCJ_VARIANT_ID = "69ec93b639cf3ab540eb0c9b"

def scrape_pcjeweller(url):
    api_key = os.environ.get("PCJ_API_KEY")
    if not api_key:
        raise RuntimeError("PCJ_API_KEY is not set (run the export command first)")
    headers = {
        "accept": "application/json",
        "origin": "https://www.pcjeweller.com",
        "referer": "https://www.pcjeweller.com/",
        "user-agent": USER_AGENT,
        "x-api-key": api_key,
    }
    api_url = f"https://pcj-web-backend-ewchp.ondigitalocean.app/prod/admin/products/variant/{PCJ_VARIANT_ID}"
    response = requests.get(api_url, headers=headers, timeout=20)
    response.raise_for_status()
    body = response.json()
    product = body.get("data", body)
    metal = making = discount = 0.0
    for part in product["priceBreakup"]:
        kind = part.get("priceType")
        if kind == "metalPrice":
            metal += float(part.get("price", 0))
        elif kind == "makingCharge":
            making += float(part.get("price", 0))
        elif kind == "promotionDiscount":
            discount += float(part.get("discountAmount", 0))
    return {
        "final_price": (metal + making - discount) * (1 + GST_RATE),
        "seller_gold_value": metal,
        "seller_making": making - discount,
    }

def scrape_bluestone(url):
    html = fetch_html(url)
    match = re.search(r'id="our_price_display"[^>]*>\s*([\d,]+)', html)
    if match:
        return {"final_price": float(match.group(1).replace(",", ""))}
    return {"final_price": find_number(r'"price"\s*:\s*"([\d.]+)"', html)}


def scrape_flipkart(url):
    html = fetch_html(url)
    return {"final_price": find_number(r'"offers":\{"price":([\d.]+),"priceCurrency":"INR"', html)}


# Which function reads which seller (names must match sellers.csv exactly)
SCRAPERS = {
    "Malabar Gold & Diamonds": scrape_malabar,
    "Kalyan Jewellers (Candere)": scrape_candere,
    "CaratLane": scrape_caratlane,
    "Joyalukkas": scrape_joyalukkas,
    "MMTC-PAMP (via Flipkart)": scrape_flipkart,
    "Senco Gold": scrape_senco,
    "PC Jeweller": scrape_pcjeweller,
    "BlueStone": scrape_bluestone,
}

# Sellers we can't read automatically: shown on the page as a link instead
LINK_ONLY = {
    "Tanishq": "Tanishq's website blocks automated price reads. Check the price on their site.",
}

# ---------- Maths ----------

def breakdown(final_price, weight_g, purity, mcx_per_10g):
    """Split a seller's final price into gold value (at MCX), markup and GST."""
    gold_value = (mcx_per_10g / 10) * weight_g * (purity / 999)
    before_gst = final_price / (1 + GST_RATE)
    gst = final_price - before_gst
    markup = before_gst - gold_value
    per_10g_999 = final_price / (weight_g * purity / 999) * 10
    return {
        "final_price": round(final_price),
        "gold_value": round(gold_value),
        "markup": round(markup),
        "markup_pct": round(markup / gold_value * 100, 1),
        "gst": round(gst),
        "per_10g_999": round(per_10g_999),
    }


# ---------- Last good prices (fallback) ----------

def load_previous():
    """Read the prices.json from the last run, so a failed seller can reuse its last good price."""
    try:
        with open("prices.json") as file:
            old = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, set()
    previous = {}
    for row in old.get("sellers", []):
        # Older files had no price_checked_at, so fall back to when that file was saved
        row.setdefault("price_checked_at", old.get("updated_at"))
        previous[row["seller"]] = row
    # Sellers that were already left out last time (so we only alert once)
    already_dropped = {f["seller"] for f in old.get("failed", []) if f.get("using_last_good_price") is False}
    return previous, already_dropped


# ---------- Run ----------

def main():
    contract = get_current_contract()
    mcx = get_mcx_price(contract)
    print("MCX contract:", contract["contract_id"], "| token", contract["token"])
    print("Live MCX Gold Ten (per 10g):", mcx)

    with open("sellers.csv") as file:
        sellers = list(csv.DictReader(file))

    now = datetime.now(IST)
    previous, already_dropped = load_previous()

    results, failed, skipped, link_only = [], [], [], []

    for seller in sellers:
        name = seller["seller"]
        if name in LINK_ONLY:
            link_only.append({
                "seller": name,
                "product": seller["product_name"],
                "url": seller["url"],
                "note": LINK_ONLY[name],
            })
            continue
        scraper = SCRAPERS.get(name)
        if scraper is None:
            skipped.append(name)
            continue
        try:
            data = scraper(seller["url"])
            if not data.get("final_price"):
                raise RuntimeError("no price found on the page")
            row = {
                "seller": name,
                "product": seller["product_name"],
                "url": seller["url"],
                "weight_g": float(seller["weight_g"]),
                "purity": float(seller["purity"]),
            }
            row.update(breakdown(data["final_price"], row["weight_g"], row["purity"], mcx))
            for key in ["seller_gold_value", "seller_making", "making_label", "in_stock"]:
                if key in data:
                    value = data[key]
                    row[key] = round(value) if isinstance(value, float) else value
            row["price_checked_at"] = now.isoformat(timespec="seconds")
            results.append(row)
        except Exception as error:
            # Fallback: reuse the last good price if it is less than 3 hours old
            old = previous.get(name)
            checked = datetime.fromisoformat(old["price_checked_at"]) if old and old.get("price_checked_at") else None
            if checked and now - checked <= STALE_LIMIT:
                row = {key: old[key] for key in ["seller", "product", "url", "weight_g", "purity"]}
                # Seller price is old, but gold value and markup use today's MCX
                row.update(breakdown(old["final_price"], row["weight_g"], row["purity"], mcx))
                for key in ["seller_gold_value", "seller_making", "making_label", "in_stock"]:
                    if key in old:
                        row[key] = old[key]
                row["price_checked_at"] = old["price_checked_at"]
                row["stale"] = True
                results.append(row)
                failed.append({"seller": name, "error": str(error), "using_last_good_price": True})
            else:
                failed.append({"seller": name, "error": str(error), "using_last_good_price": False})

    # Cheapest first, and how much more each one costs than the cheapest
    results.sort(key=lambda row: row["per_10g_999"])
    if results:
        lowest = results[0]["per_10g_999"]
        for row in results:
            row["vs_lowest"] = row["per_10g_999"] - lowest

    # Alerts: sellers left out THIS run that were not left out last run
    dropped_now = [f["seller"] for f in failed if not f["using_last_good_price"]]
    alerts = [name for name in dropped_now if name not in already_dropped]

    output = {
        "updated_at": now.isoformat(timespec="seconds"),
        "mcx": {"contract": contract["contract_id"], "price_per_10g": mcx},
        "sellers": results,
        "link_only": link_only,
        "failed": failed,
        "skipped": skipped,
        "alerts": alerts,
    }
    with open("prices.json", "w") as file:
        json.dump(output, file, indent=2)

    # A tidy summary in the terminal
    print()
    for rank, row in enumerate(results, start=1):
        note = "   (last good price from " + row["price_checked_at"][11:16] + ")" if row.get("stale") else ""
        print(f"{rank}. {row['seller']:<28} Rs {row['per_10g_999']:>9,}   markup {row['markup_pct']:>4}%   +Rs {row['vs_lowest']:,}{note}")
    for item in link_only:
        print("LINK ONLY:", item["seller"], "->", item["note"])
    for item in failed:
        status = "showing last good price" if item["using_last_good_price"] else "DROPPED (no price under 3 hours old)"
        print("FAILED:", item["seller"], "->", item["error"], "|", status)
    if skipped:
        print("Skipped:", ", ".join(skipped))
    if alerts:
        print("ALERT: newly left out ->", ", ".join(alerts))
    print()
    print("Saved prices.json at", output["updated_at"])


if __name__ == "__main__":
    main()