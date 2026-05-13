import pandas as pd
import numpy as np

FILENAME = "PIGS_2016-05-01_to_2026-05-01.parquet"

START_DATE = "2025-05-01"
END_DATE = "2026-05-01"

df = pd.read_parquet(FILENAME)

df = df.loc[START_DATE:END_DATE].copy()

df["session_date"] = df.index.date

print(df.head())

daily_rows = []

total_profit = 0
total_reverted = 0
total_non_reverted = 0

for session_date, day_df in df.groupby("session_date"):
    day_df = day_df.sort_index()

    if day_df.empty:
        continue

    daily_rows.append({
        "session_date": session_date,
        "session_open_close": day_df["close"].iloc[0],
        "session_close_close": day_df["close"].iloc[-1],
        "open_time": day_df.index[0],
        "day_df": day_df
    }) 

daily = pd.DataFrame(daily_rows)

for _, daily_row in daily.iterrows():
    print('test')

