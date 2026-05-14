import pandas as pd
import logging
import os
import time
from pathlib import Path
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd
import holidays
from signalrcore.hub_connection_builder import HubConnectionBuilder
from dotenv import load_dotenv
import time
from datetime import datetime, timezone, timedelta

load_dotenv()

API_KEY = os.getenv("PROJECT_X_API_KEY")
USER_NAME = os.getenv("PROJECT_X_USERNAME")
JWT_TOKEN = requests.post("https://api.topstepx.com/api/Auth/loginKey", json={"userName": USER_NAME, "apiKey": API_KEY}).json()["token"]
ACCOUNTS = requests.post(f"https://api.topstepx.com/api/Account/Search", headers={"Authorization": f"Bearer {JWT_TOKEN}", "Content-Type": "application/json", "Accept": "text/plain"}, json={"onlyActiveAccounts": True}).json()['accounts']
ACCOUNT_ID = ACCOUNTS[1]['id']
print(ACCOUNTS[1]['balance'])
CONTRACT_ID = "CON.F.US.HE.M26"
MARKET_HUB = f"https://rtc.topstepx.com/hubs/market"
CONTRACT_SIZE = 1
TICK_SIZE = 0.025

order_made = False

token = JWT_TOKEN

minute_candles = {}

take_profit = 0

hub = (
    HubConnectionBuilder()
    .with_url(
        f"{MARKET_HUB}?access_token={token}",
        options={
            "verify_ssl": True,
        },
    )
    .with_automatic_reconnect(
        {
            "type": "raw",
            "keep_alive_interval": 10,
            "reconnect_interval": 5,
            "max_attempts": 10,
        }
    )
    .build()
)

def classify_candle(bar):
    if bar["close"] > bar["open"]:
        return "green"
    elif bar["close"] < bar["open"]:
        return "red"
    else:
        return "neutral"

bars = {}

def get_open_orders(account_id):
    r = requests.post(
        "https://api.topstepx.com/api/Order/searchOpen",
        headers={
            "Authorization": f"Bearer {JWT_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/plain",
        },
        json={
            "accountId": account_id,
        },
    )

    print("open orders status:", r.status_code)
    print("open orders text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(data)

    return data.get("orders", [])


def is_order_still_open(account_id, order_id):
    open_orders = get_open_orders(account_id)

    for order in open_orders:
        if order["id"] == order_id:
            return True

    return False


def cancel_order(account_id, order_id):
    r = requests.post(
        "https://api.topstepx.com/api/Order/cancel",
        headers={
            "Authorization": f"Bearer {JWT_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/plain",
        },
        json={
            "accountId": account_id,
            "orderId": order_id,
        },
    )

    print("cancel status:", r.status_code)
    print("cancel text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(data)

    return data


def wait_for_fill_or_cancel(account_id, order_id, timeout_seconds=300, poll_seconds=5):
    start = time.time()

    while time.time() - start < timeout_seconds:
        if not is_order_still_open(account_id, order_id):
            print("Order is no longer open. It was probably filled/cancelled/rejected.")
            return "not_open"

        elapsed = time.time() - start
        print(f"Order still open. Elapsed: {elapsed:.0f}s")

        time.sleep(poll_seconds)

    print("Order still open after timeout. Cancelling...")
    cancel_order(account_id, order_id)
    return "cancelled"

def round_to_tick(price, tick_size=TICK_SIZE):
    return round(price / tick_size) * tick_size

def price_diff_to_ticks(price_diff, tick_size=TICK_SIZE):
    return int(round(abs(price_diff) / tick_size))

current_minute = None

def get_bar_mid_price(bar):
    return (bar["open"] + bar["close"]) / 2

def process_bars():

    direction_info = find_first_two_same_direction(bars)

    if direction_info is None:
        print("No direction found...")
        return
    
    break_info = find_break_after_direction(bars, direction_info)

    if break_info is None:
        print("Direction found, but no break found yet:", direction_info)
        return
    
    break_bar = break_info["break_bar"]
    entry_price = get_bar_mid_price(break_bar)
    take_profit = bars[direction_info["first_bucket"]]["open"]

    entry_price = round_to_tick(entry_price)
    take_profit = round_to_tick(take_profit)

    signal = {
        "original_direction": direction_info["direction"],
        "break_direction": break_info["break_direction"],
        "direction_start_bucket": direction_info["first_bucket"],
        "direction_confirm_bucket": direction_info["second_bucket"],
        "break_bucket": break_info["break_bucket"],
        "entry_price": entry_price,
        "take_profit": take_profit,
    }

    print("SIGNAL:", signal)

    # If original direction was up, break is down, so this is a short setup
    if break_info["break_direction"] == "down":
        # For short: TP should be below entry
        if take_profit >= entry_price:
            print("Invalid short setup: TP is not below entry")
            exit()

        print("VALID SHORT SETUP")
        tp_ticks = price_diff_to_ticks(entry_price - take_profit)
        data = {
            "accountId": ACCOUNT_ID,
            "contractId": CONTRACT_ID,
            "type": 1,
            "side": 1,
            "size": CONTRACT_SIZE,
            "limitPrice": entry_price,
            "takeProfitBracket": {
                "ticks": tp_ticks,
                "type": 1
            }
        }
        create_order = requests.post("https://api.topstepx.com/api/Order/Place", headers={"Authorization": f"Bearer {JWT_TOKEN}", "Content-Type": "application/json", "Accept": "text/plain"}, json=data)
        print(create_order.status_code)
        print(create_order.json())

        order_response = create_order.json()

        if not order_response.get("success"):
            print("Order failed:", order_response)
            exit()

        order_id = order_response["orderId"]
        print("Placed order:", order_id)

        wait_for_fill_or_cancel(
            account_id=ACCOUNT_ID,
            order_id=order_id,
            timeout_seconds=5 * 60,
            poll_seconds=5,
        )

        exit()
    elif break_info["break_direction"] == "up":
        # For long: TP should be above entry
        if take_profit <= entry_price:
            print("Invalid long setup: TP is not above entry")
            exit()

        print("VALID LONG SETUP")
        tp_ticks = price_diff_to_ticks(take_profit - entry_price)
        # PLACE BUY LIMIT ORDER HERE
        data = {
            "accountId": ACCOUNT_ID,
            "contractId": CONTRACT_ID,
            "type": 1,
            "side": 0,
            "size": CONTRACT_SIZE,
            "limitPrice": entry_price,
            "takeProfitBracket": {
                "ticks": tp_ticks,
                "type": 1
            }
        }
        create_order = requests.post("https://api.topstepx.com/api/Order/Place", headers={"Authorization": f"Bearer {JWT_TOKEN}", "Content-Type": "application/json", "Accept": "text/plain"}, json=data)
        print(create_order.status_code)
        print(create_order.json())

        order_response = create_order.json()

        if not order_response.get("success"):
            print("Order failed:", order_response)
            exit()

        order_id = order_response["orderId"]
        print("Placed order:", order_id)

        wait_for_fill_or_cancel(
            account_id=ACCOUNT_ID,
            order_id=order_id,
            timeout_seconds=3 * 60,
            poll_seconds=5,
        )

        exit()

    return signal

    
    
def find_break_after_direction(bars, direction_info):
    direction = direction_info["direction"]
    start_bucket = direction_info["second_bucket"]

    sorted_items = sorted(bars.items(), key=lambda x: x[0])

    for bucket, bar in sorted_items:
        # Only check bars after the 2-bar direction is established
        if bucket <= start_bucket:
            continue

        color = classify_candle(bar)

        if direction == "up" and color == "red":
            return {
                "break_direction": "down",
                "break_bucket": bucket,
                "break_bar": bar,
            }

        if direction == "down" and color == "green":
            return {
                "break_direction": "up",
                "break_bucket": bucket,
                "break_bar": bar,
            }

    return None

def find_first_two_same_direction(bars):

    global take_profit

    if len(bars) < 3:
        return None

    sorted_items = sorted(bars.items(), key=lambda x: x[0])

    previous_direction = None
    previous_bucket = None

    for bucket, bar in sorted_items:
        color = classify_candle(bar)

        # Neutral does not count, but does not reset the streak
        if color == "neutral":
            continue

        # Check for 2 same non-neutral candles, ignoring neutral candles between them
        if previous_direction is not None and color == previous_direction:
            return {
                "direction": "up" if color == "green" else "down",
                "first_bucket": previous_bucket,
                "second_bucket": bucket,
            }

        # Different non-neutral candle resets the streak
        previous_direction = color
        previous_bucket = bucket

    return None

def update_bar(trade):
    global current_minute

    price = trade["price"]
    volume = trade["volume"]

    dt = datetime.fromisoformat(trade["timestamp"])
    minute_bucket = dt.replace(second=0, microsecond=0)

    if current_minute is None:
        current_minute = minute_bucket

    if minute_bucket > current_minute:
        finished_bar = bars[current_minute]
        color = classify_candle(finished_bar)

        print("FINISHED CANDLE:")
        print(finished_bar)
        print("color:", color)

        current_minute = minute_bucket
        if len(bars.keys()) >= 3: 
            process_bars()

    if minute_bucket not in bars:
        bars[minute_bucket] = {
            "timestamp": minute_bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
        }
    else:
        bar = bars[minute_bucket]
        bar["high"] = max(bar["high"], price)
        bar["low"] = min(bar["low"], price)
        bar["close"] = price
        bar["volume"] += volume

def on_trade(*args):
    payload = args[0]
    trades = payload[1]

    for trade in trades:
        update_bar(trade)

def wait_until_next_minute():
    now = datetime.now(timezone.utc)

    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    sleep_seconds = (next_minute - now).total_seconds()

    print(f"Waiting {sleep_seconds:.2f}s until next minute:", next_minute)

    time.sleep(sleep_seconds)
    print("WAIT IS OVER. TIME TO MAKE MONIES")

def on_depth(*args):
    print("DEPTH:", args)


hub.on("GatewayTrade", on_trade)

wait_until_next_minute()

hub.start()
print("Connected to market hub")

hub.send("SubscribeContractTrades", [CONTRACT_ID])
# hub.send("SubscribeContractMarketDepth", [CONTRACT_ID])  # only if you have L2/DOM data

print(f"Subscribed to {CONTRACT_ID}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping...")
    hub.send("UnsubscribeContractTrades", [CONTRACT_ID])
    # hub.send("UnsubscribeContractMarketDepth", [CONTRACT_ID])
    hub.stop()