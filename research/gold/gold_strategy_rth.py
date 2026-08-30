import pandas as pd
import numpy as np

START_DATE = "2026-02-01"
END_DATE = "2026-05-13"
FILENAME = "GC-futures-ohlcv-01-01-2021-to-14-05-2026.parquet"
TICK_SIZE = 0.01

df = pd.read_parquet(FILENAME)

# Ensure timestamp is the index
# If Databento saved timestamp as a column instead, adjust this part.
df.index = pd.to_datetime(df.index)

# Databento timestamps are usually UTC
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC")
else:
    df.index = df.index.tz_convert("UTC")

# Convert to New York time for RTH filtering
df = df.tz_convert("America/New_York")

# GC RTH: 08:20 - 13:30 NY time
df = df.between_time("08:20", "13:30")

df = df.loc[START_DATE:END_DATE].copy()

df["bar"] = np.select([
    (df["open"] > df["close"]),
    (df["close"] > df["open"]),
    (df["close"] == df["open"])
], ["red", "green", "neutral"], default="unknown")

df["session_date"] = df.index.date

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
        if result["action"] == "long":
            result["profit"] = (take_profit - result["enter_price"])/TICK_SIZE
        elif result["action"] == "short":
            result["profit"] = (result["enter_price"] - take_profit)/TICK_SIZE
        
    else:
        result["tp_hit"] = int(tp_hit)
        final_close = closes[-10]
        final_close_time = day_df.index[-10]

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
    if result["tp_hit"] == 1:
        total_profits += result["profit"]
        if result["profit"] > max_profit:
            max_profit = result["profit"]
        
    else:
        total_profits += result["profit"]
        total_losses += result["loss"]
        if result["profit"] > max_profit:
            max_profit = result["profit"]
        if result["loss"] > max_loss:
            max_loss = result["loss"]

    print("cumulative profit:", total_profits)
    print("cumulative losses:", total_losses)

print("Total profits:", total_profits)
print("Total losses:", total_losses)
print("Maximum profit:", max_profit)
print("Maximum loss:", max_loss)      

