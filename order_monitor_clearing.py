import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.topstepx.com"

API_KEY = os.getenv("PROJECT_X_API_KEY")
USER_NAME = os.getenv("PROJECT_X_USERNAME")

CONTRACT_ID = "CON.F.US.HE.M26"

# Use UTC only.
# Change this to whatever UTC cutoff you want.
# Example: 17:59 UTC
FORCE_EXIT_HOUR_UTC = 17
FORCE_EXIT_MINUTE_UTC = 59

POLL_SECONDS = 10


def login():
    r = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={
            "userName": USER_NAME,
            "apiKey": API_KEY,
        },
    )

    print("login status:", r.status_code)
    print("login text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"Login failed: {data}")

    return data["token"]


JWT_TOKEN = login()


def headers():
    return {
        "Authorization": f"Bearer {JWT_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/plain",
    }


def get_account_id():
    return "22939567"


ACCOUNT_ID = get_account_id()


def is_force_exit_time():
    now_utc = datetime.now(timezone.utc)

    force_exit = now_utc.replace(
        hour=FORCE_EXIT_HOUR_UTC,
        minute=FORCE_EXIT_MINUTE_UTC,
        second=0,
        microsecond=0,
    )

    return now_utc >= force_exit


def search_open_positions(account_id):
    r = requests.post(
        f"{BASE_URL}/api/Position/searchOpen",
        headers=headers(),
        json={
            "accountId": account_id,
        },
    )

    print("positions status:", r.status_code)
    print("positions text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"Position search failed: {data}")

    return data.get("positions", [])


def get_open_position(account_id, contract_id):
    positions = search_open_positions(account_id)

    for position in positions:
        if position.get("contractId") == contract_id:
            return position

    return None

def close_contract(account_id, contract_id):
    r = requests.post(
        "https://api.topstepx.com/api/Position/closeContract",
        headers={
            "Authorization": f"Bearer {JWT_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/plain",
        },
        json={
            "accountId": account_id,
            "contractId": contract_id,
        },
    )

    print("closeContract status:", r.status_code)
    print("closeContract text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"closeContract failed: {data}")

    return data

def get_open_orders(account_id):
    r = requests.post(
        f"{BASE_URL}/api/Order/searchOpen",
        headers=headers(),
        json={
            "accountId": account_id,
        },
    )

    print("open orders status:", r.status_code)
    print("open orders text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"Open order search failed: {data}")

    return data.get("orders", [])


def cancel_order(account_id, order_id):
    r = requests.post(
        f"{BASE_URL}/api/Order/cancel",
        headers=headers(),
        json={
            "accountId": account_id,
            "orderId": order_id,
        },
    )

    print("cancel status:", r.status_code)
    print("cancel text:", r.text)

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"Cancel failed: {data}")

    return data


def cancel_open_orders_for_contract(account_id, contract_id):
    orders = get_open_orders(account_id)

    matching_orders = [
        order for order in orders
        if order.get("contractId") == contract_id
    ]

    if not matching_orders:
        print("No open orders to cancel for contract:", contract_id)
        return

    for order in matching_orders:
        order_id = order["id"]
        print("Cancelling open order:", order)
        cancel_order(account_id, order_id)

def main():
    print("Monitoring account:", ACCOUNT_ID)
    print("Monitoring contract:", CONTRACT_ID)
    print(
        "Force-exit UTC:",
        f"{FORCE_EXIT_HOUR_UTC:02d}:{FORCE_EXIT_MINUTE_UTC:02d}",
    )

    while True:

        position = get_open_position(ACCOUNT_ID, CONTRACT_ID)

        if position is None:
            print("No open position. Nothing to monitor.")
            return

        if is_force_exit_time():
            print("Force-exit time reached.")
            print("Cancelling working orders for this contract...")
            cancel_open_orders_for_contract(ACCOUNT_ID, CONTRACT_ID)

            print("Closing position with market order...")
            close_contract(ACCOUNT_ID, CONTRACT_ID)

            print("Done.")
            return

        print(f"Position still open. Sleeping {POLL_SECONDS}s...")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()