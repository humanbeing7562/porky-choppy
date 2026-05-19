import pandas as pd
import numpy as np

FILENAME = "GC-futures-ohlcv-01-01-2021-to-14-05-2026.parquet"

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
    df = df.drop(columns=["rtype", "publisher_id", "instrument_id", "symbol"])

    return df

df = prepare_df(FILENAME)

df["bar"] = np.select(
    [
        df["open"] > df["close"],
        df["close"] > df["open"],
        df["close"] == df["open"],
    ],
    ["red", "green", "neutral"],
    default="unknown",
)

df["ema_3"] = df["open"].ewm(span=3, adjust=False).mean()
df["ema_5"] = df["open"].ewm(span=5, adjust=False).mean()
df["ema_9"] = df["open"].ewm(span=9, adjust=False).mean()
df["ema_21"] = df["open"].ewm(span=21, adjust=False).mean()
df["ema_3_9_gap"] = df["ema_3"] - df["ema_9"]
df["ema_3_5_gap"] = df["ema_3"] - df["ema_5"]
df["ema_5_9_gap"] = df["ema_5"] - df["ema_9"]
df["ema_9_21_gap"] = df["ema_9"] - df["ema_21"]
df["ema_3_slope"] = df["ema_3"] - df["ema_3"].shift(1)
df["ema_5_slope"] = df["ema_5"] - df["ema_5"].shift(1)
df["ema_9_slope"] = df["ema_9"] - df["ema_9"].shift(1)
df["ema_21_slope"] = df["ema_21"] - df["ema_21"].shift(1)

print(df.tail(50))