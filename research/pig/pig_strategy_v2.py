import numpy as np
import pandas as pd

FILENAME = "PIGS_2016-05-01_to_2026-05-01.parquet"

df = pd.read_parquet(FILENAME)

def calculate_max_drawdown_ticks(action, entry_price, highs, lows, entry_index, exit_index, tick_size):
    """
    Maximum adverse movement while trade is open.

    Long:
        adverse move = entry_price - lowest low

    Short:
        adverse move = highest high - entry_price
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

START_DATE = "2025-05-01"
END_DATE = "2026-05-01"

TICK_SIZE = 0.0025

CONVERT_TO_NEW_YORK = True
TIMEZONE = "America/New_York"

SKIP_INVALID_TARGET_TRADES = True

df.index = pd.to_datetime(df.index)
df = df.sort_index()

if CONVERT_TO_NEW_YORK:
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(TIMEZONE)
    else:
        df.index = df.index.tz_convert(TIMEZONE)

df = df.loc[START_DATE:END_DATE].copy()

df["bar"] = np.select([
    (df["open"] > df["close"]),
    (df["close"] > df["open"]),
    (df["close"] == df["open"])
], ["red", "green", "neutral"], default="unknown")

df["session_date"] = df.index.date

# print(df.head())

daily_rows = []

for session_date, day_df in df.groupby("session_date"):
    day_df = day_df.sort_index()

    if day_df.empty:
        continue

    daily_rows.append({
        "session_date": session_date,
        "session_open_time": day_df.index[0],
        "session_end_time": day_df.index[-1],
        "day_df": day_df,
    })

daily = pd.DataFrame(daily_rows)

# print(daily.head())
results = []
win = 0
loss_but_profit = 0
loss = 0

for _, row in daily.iterrows():
    day_df = row["day_df"].copy()
    trend = None
    bars = day_df["bar"].tolist()
    closes = day_df["close"].tolist()
    opens = day_df["open"].tolist()
    lows = day_df["low"].tolist()
    highs = day_df["high"].tolist()
    for i in range(len(bars)):
        if i != 0:
            if bars[i] == "neutral" and bars[i-1] != "neutral":
                bars[i] = bars[i-1]
        elif i == 0 and bars[i] == "neutral":
            bars[i] = bars[i+1]

    start = 0
    result = None

    for i in range(1, len(bars)):
        if bars[i] != bars[i - 1]:
            end = i - 1
            length = end - start + 1

            if length >= 2 and bars[start] != "neutral":
                result = {
                    "session_date": row["session_date"],
                    "bar": bars[start],
                    "enter_price": (closes[end+1] + opens[end+1])/2,
                    "action": "long" if bars[start] == "red" else "short",
                    "take_profit": opens[start],
                    "start_index": start,
                    "end_index": end,
                    "start_time": day_df.index[start],
                    "end_time": day_df.index[end],
                    "length": length,
                }
                break

            start = i

    take_profit = result["take_profit"]

    if result["action"] == "long" and take_profit <= result["enter_price"]:
        continue
    elif result["action"] == "short" and take_profit >= result["enter_price"]:
        continue

    tp_hit = False
    tp_hit_index = None
    tp_hit_time = pd.NaT

    entry_index = result["end_index"] + 1

    for j in range(entry_index, len(day_df)):
        if lows[j] <= take_profit <= highs[j]:
            tp_hit = True
            tp_hit_index = j
            tp_hit_time = day_df.index[j]
            break

    if tp_hit:
        win += 1

        result["tp_hit"] = int(tp_hit)
        result["tp_hit_index"] = tp_hit_index
        result["tp_hit_time"] = tp_hit_time
        result["exit_price"] = take_profit
        result["exit_time"] = tp_hit_time
        result["exit_reason"] = "take_profit"

        if result["action"] == "long":
            result["profit"] = (take_profit - result["enter_price"]) / TICK_SIZE
        elif result["action"] == "short":
            result["profit"] = (result["enter_price"] - take_profit) / TICK_SIZE

        result["loss"] = 0
        exit_index = tp_hit_index

    else:
        result["tp_hit"] = int(tp_hit)

        exit_index = len(day_df) - 10 if len(day_df) >= 10 else len(day_df) - 1

        final_close = closes[exit_index]
        final_close_time = day_df.index[exit_index]

        result["exit_price"] = final_close
        result["exit_time"] = final_close_time
        result["exit_reason"] = "session_end"

        if result["action"] == "long":
            pnl = (final_close - result["enter_price"]) / TICK_SIZE
        elif result["action"] == "short":
            pnl = (result["enter_price"] - final_close) / TICK_SIZE

        if pnl >= 0:
            result["profit"] = pnl
            result["loss"] = 0
            loss_but_profit += 1
        else:
            result["profit"] = 0
            result["loss"] = abs(pnl)
            loss += 1


    max_dd_ticks, max_dd_price, max_dd_index = calculate_max_drawdown_ticks(
        action=result["action"],
        entry_price=result["enter_price"],
        highs=highs,
        lows=lows,
        entry_index=entry_index,
        exit_index=exit_index,
        tick_size=TICK_SIZE,
    )

    result["max_drawdown_ticks"] = max_dd_ticks
    result["max_drawdown_price"] = max_dd_price
    result["max_drawdown_index"] = max_dd_index
    result["max_drawdown_time"] = day_df.index[max_dd_index] if max_dd_index is not None else pd.NaT
    
    results.append(result)
    
print("Total wins:", win)
print("Total losses but profit:", loss_but_profit)
print("Total losses and deficit", loss)

print("================================================")

total_profits = 0
total_losses = 0
max_profit = 0
max_loss = 0

for result in results:
    profit = result.get("profit", 0)
    loss_amount = result.get("loss", 0)

    total_profits += profit
    total_losses += loss_amount

    if profit > max_profit:
        max_profit = profit

    if loss_amount > max_loss:
        max_loss = loss_amount

    print("session_date:", result.get("session_date"))
    print("action:", result.get("action"))
    print("profit:", profit)
    print("loss:", loss_amount)
    print("max_drawdown_ticks:", result.get("max_drawdown_ticks"))
    print("max_drawdown_price:", result.get("max_drawdown_price"))
    print("max_drawdown_time:", result.get("max_drawdown_time"))
    print("cumulative profit:", total_profits)
    print("cumulative losses:", total_losses)
    print("------------------------------------------------")

print("Total profits:", total_profits)
print("Total losses:", total_losses)
print("Maximum profit:", max_profit)
print("Maximum loss:", max_loss)      

if len(results) > 0:
    results_df = pd.DataFrame(results)

    print("Win rate:", results_df["tp_hit"].mean())
    print("Average profit ticks:", results_df["profit"].mean())
    print("Average loss ticks:", results_df["loss"].mean())
    print("Average net ticks per trade:", (results_df["profit"] - results_df["loss"]).mean())

    # Optional: save results
    output_file = f"le_strategy_results.csv"
    results_df.to_csv(output_file, index=False)
    print("Saved results to:", output_file)
else:
    print("No trades generated.")