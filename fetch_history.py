from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from scraper import USER_AGENT, get_current_contract, get_mcx_price

IST = timezone(timedelta(hours=5, minutes=30))  # India Standard Time


def get_intraday_candles(contract):
    """Today's MCX prices from Groww, one every 2 minutes: [[unix_seconds, price], ...]."""
    url = ("https://groww.in/v1/api/commodity_fo/charting_service/v2/chart/delayed/exchange/MCX/"
           f"segment/COMMODITY/{contract['token']}/daily?intervalInMinutes=2&minimal=true")
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-app-id": "growwWeb",
        "x-platform": "web",
        "referer": f"https://groww.in/commodities/futures/mcx_goldten/{contract['contract_id'].lower()}",
        "user-agent": USER_AGENT,
    }
    data = requests.get(url, headers=headers, timeout=15).json()
    return data.get("candles", [])


def mcx_price_at_bees_close(contract, bees_date):
    """Find the MCX price at (or just before) 3:30 PM IST on the day Gold BeES last traded."""
    close_time = datetime(bees_date.year, bees_date.month, bees_date.day, 15, 30, tzinfo=IST).timestamp()
    matches = [
        candle for candle in get_intraday_candles(contract)
        if datetime.fromtimestamp(candle[0], IST).date() == bees_date and candle[0] <= close_time
    ]
    if not matches:
        return None, None
    timestamp, price = matches[-1]
    return price, datetime.fromtimestamp(timestamp, IST).strftime("%H:%M")


# 1. One year of Gold BeES prices
history = yf.Ticker("GOLDBEES.NS").history(period="1y")
closes = history["Close"]
bees_price = closes.iloc[-1]
bees_date = closes.index[-1].date()

# 2. MCX price at the same moment Gold BeES closed
contract = get_current_contract()
mcx_price, matched_time = mcx_price_at_bees_close(contract, bees_date)
if mcx_price:
    print(f"MCX at {matched_time} IST on {bees_date}: {mcx_price}")
else:
    mcx_price = get_mcx_price(contract)
    print("No matching 3:30 PM price found, using live MCX instead:", mcx_price)

# 3. Ratio and scaling
ratio = mcx_price / bees_price
scaled = (closes * ratio).round(0)

print("Gold BeES on", bees_date, ":", round(bees_price, 2))
print("Ratio:", round(ratio, 1))
print()
print("Estimated price per 10g, first 3 days:")
print(scaled.head(3))
print()
print("Estimated price per 10g, last 3 days:")
print(scaled.tail(3))

# 4. Save for the chart
out = scaled.reset_index()
out.columns = ["date", "price_per_10g"]
out["date"] = out["date"].dt.strftime("%Y-%m-%d")
out.to_csv("gold_history.csv", index=False)
print()
print("Saved", len(out), "days to gold_history.csv")