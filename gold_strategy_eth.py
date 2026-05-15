import pandas as pd
import numpy as np

START_DATE = "2025-01-01"
END_DATE = "2025-05-30"
FILENAME = "GC-futures-ohlcv-01-01-2021-to-14-05-2026.parquet"

TICK_SIZE = 0.01

# Change this
SESSION = "asia"

GC_SESSIONS = {
    # Full GC Globex session, excluding 17:00-18:00 maintenance break
    # 18:00 NY -> 17:00 NY next day
    "eth_full": ("18:00", "17:00"),

    # Rough regional blocks
    "asia": ("18:00", "02:00"),
    "london": ("02:00", "08:20"),

    # COMEX active/RTH-ish window
    "rth": ("08:20", "13:30"),

    # After RTH until maintenance break
    "post_rth": ("13:30", "17:00"),
}


def calculate_max_drawdown_ticks(action, entry_price, highs, lows, entry_index, exit_index, tick_size):
    """
    Maximum adverse movement while trade is open.
    """

    highs_during_trade = highs[entry_index:exit_index + 1]
    lows_during_trade = lows[entry_index:exit_index + 1]

    if len(highs_during_trade) == 0 or len(lows_during_trade) == 0:
        return 0, None, None

    if action == "long":
        worst_price = min(lows_during_trade)
        worst_index_offset = lows_during_trade.index(worst_price)
        max_drawdown_ticks = (entry_price - worst_price) / tick_size

    elif action == "short":
        worst_price = max(highs_during_trade)
        worst_index_offset = highs_during_trade.index(worst_price)
        max_drawdown_ticks = (worst_price - entry_price) / tick_size

    else:
        return 0, None, None

    worst_index = entry_index + worst_index_offset
    max_drawdown_ticks = max(0, max_drawdown_ticks)

    return max_drawdown_ticks, worst_price, worst_index


def prepare_df(filename):
    df = pd.read_parquet(filename)

    # Ensure timestamp is the index
    df.index = pd.to_datetime(df.index)

    # Databento timestamps are usually UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # Convert to New York time for GC session logic
    df = df.sort_index()
    df = df.tz_convert("America/New_York")

    return df


def filter_gc_session(df, session_name):
    if session_name not in GC_SESSIONS:
        raise ValueError(
            f"Unknown SESSION={session_name}. "
            f"Valid sessions are: {list(GC_SESSIONS.keys())}"
        )

    start_str, end_str = GC_SESSIONS[session_name]

    start_t = pd.to_datetime(start_str).time()
    end_t = pd.to_datetime(end_str).time()
    t = df.index.time

    # Normal same-day session, e.g. 08:20 -> 13:30
    if start_t < end_t:
        mask = (t >= start_t) & (t < end_t)

    # Cross-midnight session, e.g. 18:00 -> 17:00 or 18:00 -> 02:00
    else:
        mask = (t >= start_t) | (t < end_t)

    return df.loc[mask].copy()


def assign_gc_session_date(index):
    """
    GC ETH trading day:
        18:00 NY -> 17:00 NY next day

    Example:
        2026-05-12 18:30 NY belongs to 2026-05-13 session.
        2026-05-13 10:00 NY belongs to 2026-05-13 session.

    Adding 6 hours maps the 18:00-starting session to the next date.
    """
    return (index + pd.Timedelta(hours=6)).date


df = prepare_df(FILENAME)

# Filter chosen session
df = filter_gc_session(df, SESSION)

# Correct session date for GC ETH-style sessions
df["session_date"] = assign_gc_session_date(df.index)

# Now filter date range.
# This filters by actual timestamp index, not session_date.
df = df.loc[START_DATE:END_DATE].copy()

df["bar"] = np.select(
    [
        df["open"] > df["close"],
        df["close"] > df["open"],
        df["close"] == df["open"],
    ],
    ["red", "green", "neutral"],
    default="unknown",
)

daily_rows = []

for session_date, day_df in df.groupby("session_date"):
    day_df = day_df.sort_index()

    if day_df.empty:
        continue

    daily_rows.append(
        {
            "session_date": session_date,
            "session_open_time": day_df.index[0],
            "session_end_time": day_df.index[-1],
            "day_df": day_df,
        }
    )

daily = pd.DataFrame(daily_rows)

results = []

win = 0
loss_but_profit = 0
loss = 0
skipped_no_setup = 0
skipped_bad_tp = 0

for _, row in daily.iterrows():
    day_df = row["day_df"].copy()

    if len(day_df) < 3:
        skipped_no_setup += 1
        continue

    bars = day_df["bar"].tolist()
    closes = day_df["close"].tolist()
    opens = day_df["open"].tolist()
    lows = day_df["low"].tolist()
    highs = day_df["high"].tolist()

    # Fill neutral bars using neighboring direction
    for i in range(len(bars)):
        if i != 0:
            if bars[i] == "neutral" and bars[i - 1] != "neutral":
                bars[i] = bars[i - 1]
        elif i == 0 and bars[i] == "neutral":
            bars[i] = bars[i + 1]

    start = 0
    result = None

    for i in range(1, len(bars)):
        if bars[i] != bars[i - 1]:
            end = i - 1
            length = end - start + 1

            # Need end + 1 because your entry is based on the first opposing bar
            if end + 1 >= len(day_df):
                break

            if length >= 2 and bars[start] != "neutral":
                result = {
                    "session": SESSION,
                    "session_date": row["session_date"],
                    "bar": bars[start],
                    "enter_price": (closes[end + 1]),
                    "action": "long" if bars[start] == "red" else "short",
                    "take_profit": opens[start],
                    "start_index": start,
                    "end_index": end,
                    "entry_index": end + 1,
                    "start_time": day_df.index[start],
                    "end_time": day_df.index[end],
                    "entry_time": day_df.index[end + 1],
                    "length": length,
                }
                break

            start = i

    if result is None:
        skipped_no_setup += 1
        continue

    take_profit = result["take_profit"]

    # Skip invalid TP direction
    if result["action"] == "long" and take_profit <= result["enter_price"]:
        skipped_bad_tp += 1
        continue
    elif result["action"] == "short" and take_profit >= result["enter_price"]:
        skipped_bad_tp += 1
        continue

    tp_hit = False
    tp_hit_index = None
    tp_hit_time = pd.NaT

    entry_index = result["entry_index"]

    

    for j in range(entry_index, len(day_df)):
        if lows[j] <= take_profit <= highs[j]:
            tp_hit = True
            tp_hit_index = j
            tp_hit_time = day_df.index[j]
            break

    if tp_hit:
        win += 1

        result["tp_hit"] = 1
        result["tp_hit_index"] = tp_hit_index
        result["tp_hit_time"] = tp_hit_time
        result["exit_price"] = take_profit
        result["exit_time"] = tp_hit_time
        result["exit_reason"] = "take_profit"

        if result["action"] == "long":
            result["profit"] = (take_profit - result["enter_price"]) / TICK_SIZE
        else:
            result["profit"] = (result["enter_price"] - take_profit) / TICK_SIZE

        result["loss"] = 0
        exit_index = tp_hit_index

    else:
        result["tp_hit"] = 0

        # Your original code used closes[-10].
        # Keep that behavior, but make it safe for short sessions.
        exit_i = -10 if len(day_df) >= 10 else -1

        final_close = closes[exit_i]
        final_close_time = day_df.index[exit_i]

        result["exit_price"] = final_close
        result["exit_time"] = final_close_time
        result["exit_reason"] = "session_end"

        if result["action"] == "long":
            pnl = (final_close - result["enter_price"]) / TICK_SIZE
        else:
            pnl = (result["enter_price"] - final_close) / TICK_SIZE

        if pnl >= 0:
            result["profit"] = pnl
            result["loss"] = 0
            loss_but_profit += 1
        else:
            result["profit"] = 0
            result["loss"] = abs(pnl)
            loss += 1

        exit_index = len(day_df) - 10 if len(day_df) >= 10 else len(day_df) - 1

    max_dd_ticks, max_dd_price, max_dd_index = calculate_max_drawdown_ticks(
        action=result["action"],
        entry_price=result["enter_price"],
        highs=highs,
        lows=lows,
        entry_index=entry_index,
        exit_index=exit_index,
        tick_size=TICK_SIZE
    )

    result["max_drawdown_ticks"] = max_dd_ticks
    result["max_drawdown_price"] = max_dd_price
    result["max_drawdown_index"] = max_dd_index
    result["max_drawdown_time"] = day_df.index[max_dd_index] if max_dd_index is not None else pd.NaT

    results.append(result)


print("SESSION:", SESSION)
print("Total sessions:", len(daily))
print("Total trades:", len(results))
print("Skipped no setup:", skipped_no_setup)
print("Skipped bad TP:", skipped_bad_tp)

print("Total wins:", win)
print("Total losses but profit:", loss_but_profit)
print("Total losses and deficit:", loss)

print("================================================")

total_profits = 0
total_losses = 0
max_profit = 0
max_loss = 0

for result in results:
    total_profits += result.get("profit", 0)
    total_losses += result.get("loss", 0)

    if result.get("profit", 0) > max_profit:
        max_profit = result["profit"]

    if result.get("loss", 0) > max_loss:
        max_loss = result["loss"]

    print("session_date:", result["session_date"])
    print("action:", result["action"])
    print("entry_time:", result["entry_time"])
    print("entry_price:", result["enter_price"])
    print("take_profit:", result["take_profit"])
    print("exit_time:", result["exit_time"])
    print("exit_price:", result["exit_price"])
    print("exit_reason:", result["exit_reason"])
    print("profit:", result["profit"])
    print("loss:", result["loss"])
    print("max_drawdown_ticks:", result["max_drawdown_ticks"])
    print("max_drawdown_price:", result["max_drawdown_price"])
    print("max_drawdown_time:", result["max_drawdown_time"])
    print("cumulative profit:", total_profits)
    print("cumulative losses:", total_losses)
    print("------------------------------------------------")

print("================================================")
print("Total profits:", total_profits)
print("Total losses:", total_losses)
print("Net ticks:", total_profits - total_losses)
print("Maximum profit:", max_profit)
print("Maximum loss:", max_loss)

if len(results) > 0:
    results_df = pd.DataFrame(results)

    print("Win rate:", results_df["tp_hit"].mean())
    print("Average profit ticks:", results_df["profit"].mean())
    print("Average loss ticks:", results_df["loss"].mean())
    print("Average net ticks per trade:", (results_df["profit"] - results_df["loss"]).mean())

    # Optional: save results
    output_file = f"gc_strategy_results_{SESSION}.csv"
    results_df.to_csv(output_file, index=False)
    print("Saved results to:", output_file)
else:
    print("No trades generated.")